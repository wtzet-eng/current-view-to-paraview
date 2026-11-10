def classFactory(iface):
    from .plugin import ViewPlugin
    return ViewPlugin(iface)
