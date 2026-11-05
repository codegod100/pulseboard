// A thin scroll indicator that can be dragged.
import QtQuick

Rectangle {
    id: bar
    required property Flickable flick
    readonly property real ratio: flick.height / Math.max(flick.contentHeight, 1)
    visible: ratio < 1
    anchors.right: parent.right
    anchors.rightMargin: 2
    width: drag.containsMouse || drag.pressed ? 8 : 5
    radius: width / 2
    y: flick.visibleArea.yPosition * flick.height
    height: Math.max(24, flick.visibleArea.heightRatio * flick.height)
    color: Theme.muted
    opacity: drag.containsMouse || drag.pressed || flick.moving ? 0.6 : 0.25
    Behavior on opacity { NumberAnimation { duration: 150 } }
    MouseArea {
        id: drag
        anchors.fill: parent
        anchors.margins: -4
        hoverEnabled: true
        property real startY: 0
        property real startContent: 0
        onPressed: (m) => { startY = mapToItem(bar.flick, 0, m.y).y; startContent = bar.flick.contentY }
        onPositionChanged: (m) => {
            if (!pressed) return
            const dy = mapToItem(bar.flick, 0, m.y).y - startY
            const max = bar.flick.contentHeight - bar.flick.height
            bar.flick.contentY = Math.max(0, Math.min(max, startContent + dy / bar.ratio))
        }
    }
}
