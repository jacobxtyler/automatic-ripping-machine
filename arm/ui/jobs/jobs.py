"""
ARM route blueprint for jobs pages
Covers
- jobdetail [GET]
- jobdetailload [POST]
- titlesearch [GET]
- custometitle [GET]
- gettitle / customtitle [GET]
- updatetitle [GET]
- activerips [GET]
- changeparams [GET]
- list_titles [GET]
- json [JSON GET]
"""

import json
from flask_login import LoginManager, login_required, current_user  # noqa: F401
from flask import render_template, request, Blueprint, flash, redirect, url_for
from werkzeug.routing import ValidationError

import arm.ui.utils as ui_utils
from arm.ui import app, db, constants, json_api
from arm.models.job import Job, JobState
from arm.models.notifications import Notifications
import arm.config.config as cfg
from arm.ripper import open_library
from arm.ui.forms import TitleSearchForm, ChangeParamsForm, TrackFormDynamic

route_jobs = Blueprint('route_jobs', __name__,
                       template_folder='templates',
                       static_folder='../static')

OPEN_LIBRARY_COVER_URL = "https://covers.openlibrary.org/b/id/{}-L.jpg"


def _positive_int(value, field_name):
    """Convert a form value to a positive integer."""
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive number.") from error
    if number < 1:
        raise ValueError(f"{field_name} must be a positive number.")
    return number


def _optional_positive_int(value, field_name):
    """Convert an optional form value to a positive integer or None."""
    if value in (None, ""):
        return None
    return _positive_int(value, field_name)


def update_audiobook_metadata(job, form_data):
    """Apply submitted audiobook metadata to a job."""
    required_fields = {
        'audiobook_author': form_data.get('audiobook_author', '').strip(),
        'audiobook_title': form_data.get('audiobook_title', '').strip(),
        'audiobook_disc_number': form_data.get('audiobook_disc_number', '').strip(),
    }
    missing = [field for field, value in required_fields.items() if not value]
    if missing:
        raise ValueError("Author, title, and disc number are required for audiobook jobs.")

    job.audiobook_author = required_fields['audiobook_author']
    job.title = job.title_manual = ui_utils.clean_for_filename(required_fields['audiobook_title'])
    job.audiobook_disc_number = _positive_int(required_fields['audiobook_disc_number'], "Disc number")
    job.audiobook_total_discs = _optional_positive_int(form_data.get('audiobook_total_discs'), "Total discs")
    job.year = job.year_manual = form_data.get('audiobook_year') or None
    job.open_library_work_key = form_data.get('open_library_work_key') or None
    job.open_library_cover_id = form_data.get('open_library_cover_id') or None
    job.hasnicetitle = True
    job.manual_start = True


def is_manual_waiting_job(job):
    """Return True when a manual job is waiting for user input."""
    return bool(
        job
        and job.manual_mode
        and job.status == JobState.MANUAL_WAIT_STARTED.value
        and not job.manual_start
    )


def apply_manual_track_selection(job, submitted_tracks):
    """Validate and atomically stage a manual video title selection."""
    if not is_manual_waiting_job(job):
        raise ValueError("This job is no longer waiting for title selection.")

    job_tracks = {track.track_id: track for track in job.tracks.all()}
    selected_ids = set()
    submitted_ids = set()
    for track_id, selected in submitted_tracks:
        try:
            track_id = int(track_id)
        except (TypeError, ValueError) as error:
            raise ValueError("The submitted title selection is invalid.") from error
        if track_id in submitted_ids or track_id not in job_tracks:
            raise ValueError("The submitted title selection contains an invalid title.")
        submitted_ids.add(track_id)
        if selected:
            selected_ids.add(track_id)

    if not selected_ids:
        raise ValueError("Select at least one title to rip.")

    for track_id, track in job_tracks.items():
        track.process = track_id in selected_ids
    job.manual_start = True
    return len(selected_ids)


def _track_status(job, track):
    """Return a user-facing track status without relying on eligibility's `ripped` flag."""
    if track.status == JobState.FAILURE.value or (
            job.status == JobState.FAILURE.value and track.process):
        return "Failed", "danger"
    if track.status == JobState.SUCCESS.value:
        return "Completed", "success"
    if job.status == JobState.SUCCESS.value and track.process:
        return "Completed", "success"
    if track.process:
        return "Selected", "primary"
    return "Skipped", "secondary"


def _format_duration(length, is_audio=False):
    if not length:
        return "—"
    seconds = round(length / 1000) if is_audio else int(length)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _format_filesize(filesize):
    if not filesize:
        return "—"
    value = float(filesize)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return "—"


def build_track_views(job, tracks):
    """Build display data and duplicate-runtime comparisons for track rows."""
    is_audio = job.disctype in ("music", "audiobook")
    try:
        minimum = int(job.config.MINLENGTH)
    except (TypeError, ValueError):
        minimum = 0
    try:
        maximum = int(job.config.MAXLENGTH)
    except (TypeError, ValueError):
        maximum = 99999

    recommended = next((track for track in tracks if track.main_feature), None)
    if recommended is None and tracks and not is_audio:
        recommended = max(
            tracks,
            key=lambda track: (
                track.chapters or 0,
                track.filesize or 0,
                -int(track.track_number) if str(track.track_number).isdigit() else 0,
            ),
        )

    comparison_fields = (
        "chapters", "filesize", "playlist_id", "segment_count", "segment_map",
        "video_resolution", "video_codec", "audio_languages", "subtitle_languages",
        "aspect_ratio", "fps", "source", "output_filename",
    )

    def comparison_value(track, field):
        if field == "output_filename":
            return track.new_filename or track.filename or track.orig_filename or None
        return getattr(track, field, None) or None

    runtime_groups = {}
    for track in tracks:
        runtime_groups.setdefault(track.length, []).append(track)
    differing_by_length = {}
    for length, group in runtime_groups.items():
        if length and len(group) > 1:
            differing_by_length[length] = {
                field for field in comparison_fields
                if len({comparison_value(track, field) for track in group}) > 1
            }

    views = []
    for track in tracks:
        status, status_class = _track_status(job, track)
        views.append({
            "track": track,
            "duration": _format_duration(track.length, is_audio),
            "filesize": _format_filesize(track.filesize),
            "chapters": track.chapters or "—",
            "fps": f"{track.fps:g}" if track.fps else "—",
            "aspect": track.aspect_ratio or "—",
            "resolution": track.video_resolution or "—",
            "source": track.source or "—",
            "output_filename": track.new_filename or track.filename or track.orig_filename or "—",
            "recommended": recommended is track,
            "meets_minimum": bool(track.length and track.length >= minimum),
            "eligible": bool(track.length and minimum <= track.length <= maximum),
            "equal_runtime": track.length in differing_by_length,
            "differing_fields": differing_by_length.get(track.length, set()),
            "status": status,
            "status_class": status_class,
        })
    return views


def is_manual_audio_job(job):
    """Return True when a job is waiting for manual Music/Audiobook input."""
    return bool(
        is_manual_waiting_job(job)
        and job.disctype in ("music", "audiobook")
    )


def audiobook_cover_url(cover_id):
    """Return an Open Library cover URL for a cover id, or None."""
    cover_id = str(cover_id or "").strip()
    return OPEN_LIBRARY_COVER_URL.format(cover_id) if cover_id else None


def build_audiobook_query(title, author=""):
    """Build the Open Library query string from title/author input."""
    return " ".join(part.strip() for part in (author, title) if part and part.strip())


def update_audiobook_title(job, form_data):
    """Apply audiobook metadata from a title-search selection or manual save."""
    update_audiobook_metadata(job, form_data)
    job.disctype = "audiobook"
    job.video_type = job.video_type_manual = "audiobook"
    job.imdb_id = job.imdb_id_manual = None
    job.poster_url = job.poster_url_manual = audiobook_cover_url(job.open_library_cover_id)


def title_search_defaults(job):
    """Return default field values for the shared title-search form."""
    return {
        "media_type": "audiobook" if job.disctype == "audiobook" else "video",
        "title": job.title_manual or job.title or "",
        "author": job.audiobook_author or "",
        "year": job.year_manual or job.year or "",
        "audiobook_disc_number": job.audiobook_disc_number,
        "audiobook_total_discs": job.audiobook_total_discs,
        "open_library_work_key": job.open_library_work_key or "",
        "open_library_cover_id": job.open_library_cover_id or "",
    }


def audiobook_search_form_data(args):
    """Normalize audiobook search values from request arguments."""
    return {
        "media_type": "audiobook",
        "title": (args.get("title") or "").strip(),
        "author": (args.get("author") or "").strip(),
        "year": (args.get("year") or "").strip(),
        "audiobook_disc_number": (args.get("audiobook_disc_number") or "").strip(),
        "audiobook_total_discs": (args.get("audiobook_total_discs") or "").strip(),
        "open_library_work_key": (args.get("open_library_work_key") or "").strip(),
        "open_library_cover_id": (args.get("open_library_cover_id") or "").strip(),
    }


def update_audio_manual_choice(job, form_data):
    """Apply the manual Music/Audiobook choice for an audio CD."""
    audio_disc_type = form_data.get('audio_disc_type')
    if audio_disc_type not in ("music", "audiobook"):
        raise ValueError("Audio disc type must be Music or Audiobook.")

    job.disctype = audio_disc_type
    if audio_disc_type == "music":
        job.manual_start = True
    else:
        job.hasnicetitle = False
        job.manual_start = False


def job_uses_video_metadata(job):
    """Return True when a job should use movie/show metadata lookups."""
    return job.disctype in ("dvd", "bluray")


def get_jobdetail_metadata(job):
    """Return metadata for the job detail page without querying video providers for audio jobs."""
    if not job_uses_video_metadata(job):
        return {"Ratings": [], "Plot": "", "background_url": None}
    search_results = ui_utils.metadata_selector("get_details", job.title, job.year, job.imdb_id)
    return search_results or {"Ratings": [], "Plot": "", "background_url": None}


def validate_title_search_input(job, form_data):
    """Validate title search input for video and audiobook searches."""
    media_type = form_data.get("media_type")

    if is_manual_audio_job(job) and media_type == "music":
        return

    if not (form_data.get("title") or "").strip():
        raise ValueError("Title is required.")

    if media_type == "audiobook" and not (form_data.get("audiobook_disc_number") or "").strip():
        raise ValueError("Disc number is required for audiobook jobs.")


@route_jobs.route('/jobdetail')
@login_required
def jobdetail():
    """
    Page for showing in-depth details about a job

    Shows Job/Config/Track class details
    displays them in a clear and easy to ready format
    """
    manual_edit = False

    # Initialise form
    track_form = TrackFormDynamic()

    job_id = request.args.get('job_id')
    if (job := Job.query.get(job_id)) is None:
        raise ValueError('Job not found')

    # Check if a manual job, waiting for input and user has not provided input
    if is_manual_waiting_job(job):
        manual_edit = True

    # Get Job and Track data
    tracks = job.tracks.all()
    track_views = build_track_views(job, tracks)
    track_form.track_ref.min_entries = len(tracks)
    app.logger.debug(f"Found [{len(tracks)}] tracks")
    track_form.track_ref.entries.clear()
    # Loop through each track entry and build the WTForms dynamically
    for track_row in tracks:
        track_form.track_ref.append_entry({'track_ref': track_row.track_id,
                                           'checkbox': track_row.process})
    # For Jobs that are not waiting and in manual mode, disable the process checkbox
    if not manual_edit:
        for entry in track_form.track_ref.entries:
            entry.checkbox.render_kw = {'disabled': 'disabled'}

    search_results = get_jobdetail_metadata(job)

    if search_results and 'Error' not in search_results:
        job.plot = search_results['Plot'] if 'Plot' in search_results else "There was a problem getting the plot"
        job.background = search_results['background_url'] if 'background_url' in search_results else None

    return render_template('jobdetail.html',
                           jobs=job,
                           tracks=tracks,
                           track_views=track_views,
                           s=search_results,
                           manual_edit=manual_edit,
                           form=track_form)


@route_jobs.route('/jobdetailload', methods=['POST'])
@login_required
def jobdetail_load():
    """
    Process updated track ID fields against a job and load to the ARM database if valid
    All data passed via POST
    """
    # Initialise form
    track_form = TrackFormDynamic()

    job_id = request.args.get('job_id')
    job = Job.query.get(job_id)
    if job is None:
        flash("Job not found", "danger")
        return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

    if request.method == 'POST' and request.form.get('audio_disc_type'):
        if not is_manual_waiting_job(job):
            flash("This job is no longer waiting for manual input.", "danger")
            return redirect(url_for('route_jobs.jobdetail', job_id=job_id))
        try:
            update_audio_manual_choice(job, request.form)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

        db.session.commit()
        if job.disctype == "audiobook":
            flash("Audiobook selected. Use Title Search to find or enter audiobook metadata.", "success")
        else:
            flash("Music CD selected", "success")
        return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

    if request.method == 'POST' and job.disctype == "audiobook":
        if not is_manual_waiting_job(job):
            flash("This job is no longer waiting for manual input.", "danger")
            return redirect(url_for('route_jobs.jobdetail', job_id=job_id))
        try:
            update_audiobook_metadata(job, request.form)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

        db.session.commit()
        app.logger.debug(f"Setting [{job.job_id}] to [{job.manual_start}], lets get ripping")
        flash("Audiobook metadata was updated", "success")
        return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

    # Data passed back from webpage, process and update track fields
    if request.method == 'POST' and track_form.validate_on_submit():
        app.logger.debug(f"Job id [{job.job_id}]")
        app.logger.debug(f"Returned [{len(track_form.track_ref.entries)}] tracks")
        submitted_tracks = [
            (track_row.data["track_ref"], track_row.data["checkbox"])
            for track_row in track_form.track_ref.entries
        ]
        try:
            selected_count = apply_manual_track_selection(job, submitted_tracks)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for('route_jobs.jobdetail', job_id=job_id))
        db.session.commit()
        app.logger.debug(f"Setting [{job.job_id}] to [{job.manual_start}], lets get ripping")
        flash(f"{selected_count} title(s) selected for ripping", "success")
    elif request.method == 'POST':
        flash("The submitted title selection is invalid.", "danger")

    return redirect(url_for('route_jobs.jobdetail', job_id=job_id))


@route_jobs.route('/titlesearch')
@login_required
def title_search():
    """
    The initial search page
    """
    job_id = request.args.get('job_id')
    job = Job.query.get(job_id)
    defaults = title_search_defaults(job)
    if is_manual_audio_job(job):
        defaults["media_type"] = request.args.get("media_type") or (
            "audiobook" if job.disctype == "audiobook" else "music"
        )
    form = TitleSearchForm(data={**defaults, **request.args.to_dict()})

    if request.args.get("save"):
        try:
            validate_title_search_input(job, request.args)
        except ValueError as error:
            flash(str(error), "danger")
            return render_template('titlesearch.html', title='Update Title', form=form, job=job,
                                   audio_manual_job=is_manual_audio_job(job))

        if is_manual_audio_job(job) and request.args.get("media_type") == "music":
            update_audio_manual_choice(job, {"audio_disc_type": "music"})
            db.session.commit()
            flash("Music CD selected", "success")
            return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

        flash(f'Search for {request.args.get("title")}, year={request.args.get("year")}', 'success')
        return redirect(url_for('route_jobs.list_titles',
                                title=request.args.get("title"),
                                year=request.args.get("year"),
                                author=request.args.get("author"),
                                media_type=request.args.get("media_type"),
                                audiobook_disc_number=request.args.get("audiobook_disc_number"),
                                audiobook_total_discs=request.args.get("audiobook_total_discs"),
                                open_library_work_key=request.args.get("open_library_work_key"),
                                open_library_cover_id=request.args.get("open_library_cover_id"),
                                job_id=job_id))

    if request.args.get("manual_save"):
        form_data = audiobook_search_form_data(request.args)
        try:
            validate_title_search_input(job, request.args)
            update_audiobook_title(job, {
                "audiobook_author": form_data["author"],
                "audiobook_title": form_data["title"],
                "audiobook_disc_number": form_data["audiobook_disc_number"],
                "audiobook_total_discs": form_data["audiobook_total_discs"],
                "audiobook_year": form_data["year"],
                "open_library_work_key": form_data["open_library_work_key"],
                "open_library_cover_id": form_data["open_library_cover_id"],
            })
        except ValueError as error:
            flash(str(error), "danger")
            return render_template('titlesearch.html', title='Update Title', form=form, job=job,
                                   audio_manual_job=is_manual_audio_job(job))

        db.session.commit()
        flash("Audiobook metadata was updated", "success")
        return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

    return render_template('titlesearch.html', title='Update Title', form=form, job=job,
                           audio_manual_job=is_manual_audio_job(job))


@route_jobs.route('/customTitle')
@login_required
def customtitle():
    """
    For setting custom title for series with multiple discs
    """
    job_id = request.args.get('job_id')
    ui_utils.job_id_validator(job_id)
    job = Job.query.get(job_id)
    form = TitleSearchForm(obj=job)
    if request.args.get("title"):
        args = {
            'title': request.args.get("title"),
            'title_manual': request.args.get("title"),
            'year': request.args.get("year")
        }
        notification = Notifications(f"Job: {job.job_id} was updated",
                                     f'Title: {job.title} ({job.year}) was updated to '
                                     f'{request.args.get("title")} ({request.args.get("year")})')
        db.session.add(notification)
        ui_utils.database_updater(args, job)
        flash(f'Custom title changed. Title={job.title}, Year={job.year}.', "success")
        return redirect(url_for('home'))
    return render_template('customTitle.html', title='Change Title', form=form, job=job)


@route_jobs.route('/gettitle')
@route_jobs.route('/select_title')
@login_required
def gettitle():
    """
    Used to display plot info from the search result page when the user clicks the title
    and to forward the user to save the selected details

    This was also used previously for the getdetails page but it no longer needed there
    """
    imdb_id = request.args.get('imdbID').strip() if request.args.get('imdbID') else None
    job_id = request.args.get('job_id').strip() if request.args.get('job_id') else None
    if imdb_id == "" or imdb_id is None:
        app.logger.debug("gettitle - no imdb supplied")
        flash("No imdb supplied", "danger")
        raise ValidationError("No imdb supplied")
    if job_id == "" or job_id is None:
        app.logger.debug("gettitle - no job supplied")
        flash(constants.NO_JOB, "danger")
        raise ValidationError(constants.NO_JOB)
    dvd_info = ui_utils.metadata_selector("get_details", None, None, imdb_id)
    return render_template('showtitle.html', results=dvd_info, job_id=job_id)


@route_jobs.route('/updatetitle')
@login_required
def updatetitle():
    """
    used to save the details from the search
    Example URL
    updatetitle?title=Home&amp;year=2015&amp;imdbID=tt2224026&amp;type=movie&amp;
    poster=http://image.tmdb.org/t/p/original/usFenYnk6mr8C62dB1MoAfSWMGR.jpg&amp;job_id=109

    args
    title - new movie title
    year - new movie year
    imdbID - new movie IMDB reference
    type - new movie type
    poster - new movie poster URL
    job_id - job to update
    """
    #

    job_id = request.args.get('job_id')
    job = Job.query.get(job_id)
    old_title = job.title
    old_year = job.year
    app.logger.debug(f"Old Title and Year: {old_title}, {old_year}")

    if request.args.get("media_type") == "audiobook":
        form_data = audiobook_search_form_data(request.args)
        try:
            update_audiobook_title(job, {
                "audiobook_author": form_data["author"],
                "audiobook_title": form_data["title"],
                "audiobook_disc_number": form_data["audiobook_disc_number"],
                "audiobook_total_discs": form_data["audiobook_total_discs"],
                "audiobook_year": form_data["year"],
                "open_library_work_key": form_data["open_library_work_key"],
                "open_library_cover_id": form_data["open_library_cover_id"],
            })
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for('route_jobs.title_search', job_id=job_id, media_type='audiobook'))

        notification = Notifications(f"Job: {job.job_id} was updated",
                                     f'Title: {old_title} ({old_year}) was updated to '
                                     f'{request.args.get("title")} ({request.args.get("year")})')
        db.session.add(notification)
        db.session.commit()
        flash(f'Audiobook metadata updated to {request.args.get("title")} ({request.args.get("year")})', "success")
        return redirect(url_for('route_jobs.jobdetail', job_id=job_id))

    app.logger.debug(f"New Title: {request.args.get('title')}")
    new_title = ui_utils.clean_for_filename(request.args.get('title'))
    app.logger.debug(f"Cleaned New Title: {new_title}")
    job.title = job.title_manual = new_title

    app.logger.debug(f"New Year: {request.args.get('year')}")
    app.logger.debug(f"New Type: {request.args.get('type')}")
    app.logger.debug(f"New IMDB: {request.args.get('imdbID')}")
    app.logger.debug(f"New Poster: {request.args.get('poster')}")

    job.year = job.year_manual = request.args.get('year')
    job.video_type = job.video_type_manual = request.args.get('type')
    job.imdb_id = job.imdb_id_manual = request.args.get('imdbID')
    job.poster_url = job.poster_url_manual = request.args.get('poster')

    job.hasnicetitle = True
    notification = Notifications(f"Job: {job.job_id} was updated",
                                 f'Title: {old_title} ({old_year}) was updated to '
                                 f'{request.args.get("title")} ({request.args.get("year")})')
    db.session.add(notification)
    db.session.commit()
    flash(f'Title: {old_title} ({old_year}) was updated to '
          f'{request.args.get("title")} ({request.args.get("year")})', "success")
    return redirect("/")


@route_jobs.route('/activerips')
@login_required
def rips():
    """
    This no longer works properly because of the 'transcoding' status
    """
    active_jobs = Job.query.filter_by(~Job.finished)
    return render_template('activerips.html', jobs=active_jobs)


@route_jobs.route('/changeparams')
@login_required
def changeparams():
    """
    For updating Config params or changing/correcting job.disctype manually
    """
    config_id = request.args.get('config_id')
    job = Job.query.get(config_id)
    config = job.config
    form = ChangeParamsForm(obj=config)
    return render_template('changeparams.html', title='Change Parameters', form=form, config=config)


@route_jobs.route('/list_titles')
@login_required
def list_titles():
    """
    The search results page

    This will display the returned search results from OMDB or TMDB from the users input search
    """
    title = request.args.get('title').strip() if request.args.get('title') else ''
    year = request.args.get('year').strip() if request.args.get('year') else ''
    job_id = request.args.get('job_id').strip() if request.args.get('job_id') else ''
    if job_id == "":
        app.logger.debug("list_titles - no job supplied")
        flash(constants.NO_JOB, "danger")
        raise ValidationError
    job = Job.query.get(job_id)
    media_type = request.args.get('media_type') or ('audiobook' if job.disctype == 'audiobook' else 'video')
    author = request.args.get('author', '').strip()
    disc_number = request.args.get('audiobook_disc_number', '').strip()
    total_discs = request.args.get('audiobook_total_discs', '').strip()
    work_key = request.args.get('open_library_work_key', '').strip()
    cover_id = request.args.get('open_library_cover_id', '').strip()
    form_data = {
        **title_search_defaults(job),
        'media_type': media_type,
        'title': title,
        'author': author,
        'year': year,
        'audiobook_disc_number': disc_number,
        'audiobook_total_discs': total_discs,
        'open_library_work_key': work_key,
        'open_library_cover_id': cover_id,
    }
    form = TitleSearchForm(data=form_data)

    if media_type == 'audiobook':
        search_query = build_audiobook_query(title, author)
        search_results = {"Search": open_library.search(search_query)}
        if len(search_results["Search"]) < 1:
            flash(f"No audiobook search results found for {search_query}", 'danger')
    else:
        search_results = ui_utils.metadata_selector("search", title, year)
        if search_results is None or 'Error' in search_results or (
                'Search' in search_results and len(search_results['Search']) < 1):
            app.logger.debug("No results found. Trying without year")
            flash(f"No search results found for {title} ({year})<br/> Trying without year", 'danger')
            search_results = ui_utils.metadata_selector("search", title, "")

        if search_results is None or 'Error' in search_results or (
                'Search' in search_results and len(search_results['Search']) < 1):
            flash(f"No search results found for {title}", 'danger')
    return render_template('list_titles.html', results=search_results, job_id=job_id,
                           form=form, title=title, year=year, author=author, media_type=media_type,
                           audiobook_disc_number=disc_number, audiobook_total_discs=total_discs,
                           open_library_work_key=work_key, open_library_cover_id=cover_id)


@route_jobs.route('/json', methods=['GET'])
def feed_json():
    """
    json mini API
    This is used for all api/ajax calls this makes thing easier to read/code for
    Adding a new function to the api is as simple as adding a new elif where GET[mode]
    is your call
    You can then add a function inside utils to deal with the request
    """
    # Check if users is authenticated
    # Return data when authenticated, but allow basic job info when not
    authenticated = ui_utils.authenticated_state()
    mode = str(request.args.get('mode'))
    return_json = {'mode': mode, 'success': False}

    if authenticated:
        # Hold valid data (post/get data) we might receive from pages - not in here ? it's going to throw a key error
        valid_data = {
            'j_id': request.args.get('job'),
            'searchq': request.args.get('q'),
            'logpath': cfg.arm_config['LOGPATH'],
            'fail': 'fail',
            'success': 'success',
            'joblist': 'joblist',
            'mode': mode,
            'config_id': request.args.get('config_id'),
            'notify_id': request.args.get('notify_id'),
            'notify_timeout': {'funct': json_api.get_notify_timeout, 'args': ('notify_timeout',)},
            'restart': {'funct': json_api.restart_ui, 'args': ()},
        }
        # Valid modes that should trigger functions
        valid_modes = {
            'delete': {'funct': json_api.delete_job, 'args': ('j_id', 'mode')},
            'abandon': {'funct': json_api.abandon_job, 'args': ('j_id',)},
            'full': {'funct': json_api.generate_log, 'args': ('logpath', 'j_id')},
            'search': {'funct': json_api.search, 'args': ('searchq',)},
            'audiobook_search': {'funct': json_api.audiobook_search, 'args': ('searchq',)},
            'getfailed': {
                'funct': json_api.get_x_jobs,
                'args': (JobState.FAILURE.value,),
            },
            'getsuccessful': {
                'funct': json_api.get_x_jobs,
                'args': (JobState.SUCCESS.value,),
            },
            'fixperms': {'funct': ui_utils.fix_permissions, 'args': ('j_id',)},
            'joblist': {'funct': json_api.get_x_jobs, 'args': ('joblist',)},
            'send_item': {'funct': ui_utils.send_to_remote_db, 'args': ('j_id',)},
            'change_job_params': {'funct': json_api.change_job_params, 'args': ('config_id',)},
            'read_notification': {'funct': json_api.read_notification, 'args': ('notify_id',)},
            'notify_timeout': {'funct': json_api.get_notify_timeout, 'args': ('notify_timeout',)}
        }
    else:
        valid_data = {
            'joblist': 'joblist',
        }
        valid_modes = {
            'joblist': {'funct': json_api.get_x_jobs, 'args': ('joblist',)},
        }
    # prepare JSON data
    if mode in valid_modes:
        args = [valid_data[x] for x in valid_modes[mode]['args']]
        return_json = valid_modes[mode]['funct'](*args)
    return_json['notes'] = json_api.get_notifications()

    # return JSON data
    return app.response_class(response=json.dumps(return_json, indent=4, sort_keys=True),
                              status=200,
                              mimetype=constants.JSON_TYPE)
