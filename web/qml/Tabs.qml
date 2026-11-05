// Unread / All / Read.
import QtQuick

Rectangle {
    id: root
    property var labels: []
    property int current: 0
    signal picked(int index)

    implicitWidth: row.implicitWidth + 6
    implicitHeight: 36
    radius: Theme.radius
    color: Theme.secondary

    Row {
        id: row
        x: 3; y: 3
        height: parent.height - 6
        Repeater {
            model: root.labels
            Rectangle {
                required property int index
                required property string modelData
                width: label.implicitWidth + 24
                height: row.height
                radius: Theme.radius - 2
                color: root.current === index ? (Theme.dark ? Qt.rgba(1, 1, 1, 0.08) : Theme.card) : "transparent"
                border.width: root.current === index && Theme.dark ? 1 : 0
                border.color: Theme.inputBorder
                Text { textFormat: Text.PlainText;
                    id: label
                    anchors.centerIn: parent
                    text: modelData
                    color: root.current === index ? Theme.foreground : Theme.muted
                    font.pixelSize: Theme.fontSize
                    font.weight: Font.Medium
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.picked(index)
                }
            }
        }
    }
}
