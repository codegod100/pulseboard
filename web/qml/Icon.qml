// A lucide icon, drawn from its SVG path so no image format is needed.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property string name
    property color color: Theme.foreground
    property real size: 18
    implicitWidth: size
    implicitHeight: size

    readonly property var paths: ({
        "refresh": "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5",
        "check": "M20 6L9 17l-5-5",
        "check-all": "M18 6L7 17l-5-5M22 10l-7.5 7.5L13 16",
        "unread": "M22 13V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9M22 7l-10 6L2 7M16 18a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
        "rss": "M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16M4 19a1 1 0 1 0 2 0a1 1 0 1 0-2 0",
        "search": "M3 11a8 8 0 1 0 16 0a8 8 0 1 0-16 0M21 21l-4.3-4.3",
        "x": "M18 6L6 18M6 6l12 12",
        "back": "M12 19l-7-7 7-7M19 12H5",
        "plus": "M12 5v14M5 12h14",
        "trash": "M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",
        "pencil": "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z",
        "upload": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
        "copy": "M10 8h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2ZM4 16a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2"
    })

    Shape {
        width: 24
        height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.color
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.paths[root.name] || "" }
        }
    }
}
