(function () {
    "use strict";

    function setDiagnostic(name, value) {
        document.querySelectorAll('[data-diagnostic="' + name + '"]').forEach(function (element) {
            element.textContent = value === null || value === undefined ? "Unavailable" : value;
        });
    }

    function renderHardware(support) {
        ["intel", "nvidia", "amd"].forEach(function (name) {
            const value = support ? support[name] : null;
            document.querySelectorAll('[data-diagnostic-hw="' + name + '"]').forEach(function (element) {
                if (value === true) {
                    element.textContent = "Supported";
                    element.className = "text-success";
                } else if (value === false) {
                    element.textContent = "Unsupported";
                    element.className = "text-danger";
                } else {
                    element.textContent = "Unavailable";
                    element.className = "text-muted";
                }
            });
        });
    }

    function renderDiagnostics(data) {
        setDiagnostic("local_version", data.local_version);
        setDiagnostic("git_commit", data.git_commit);
        renderHardware(data.hw_support);

        let updateMessage = "Update status unavailable";
        if (data.update_available === true) {
            updateMessage = "Update available";
            if (data.remote_version) {
                updateMessage += " (version " + data.remote_version + ")";
            }
        } else if (data.update_available === false) {
            updateMessage = "Up to date";
        }
        setDiagnostic("update_message", updateMessage);
    }

    function markUnavailable() {
        renderDiagnostics({
            local_version: null,
            git_commit: null,
            update_available: null,
            remote_version: null,
            hw_support: null
        });
    }

    function loadDiagnostics() {
        fetch("/settings/diagnostics", {credentials: "same-origin"})
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("diagnostics request failed");
                }
                return response.json();
            })
            .then(function (data) {
                if (data.status !== "refreshing" || data.checked_at !== null) {
                    renderDiagnostics(data);
                }
                if (data.status === "refreshing") {
                    window.setTimeout(loadDiagnostics, 1000);
                }
            })
            .catch(markUnavailable);
    }

    loadDiagnostics();
}());
