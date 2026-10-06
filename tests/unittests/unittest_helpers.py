def close_app_widgets(app):
    widgets = [
        widget
        for attribute in ("console_widget", "logging_widget", "ui")
        if (widget := getattr(app, attribute, None)) is not None
    ]
    for widget in widgets:
        widget.hide()
    app.qtapp.processEvents()