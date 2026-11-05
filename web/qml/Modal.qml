// A dialog over a dimmed page. Escape or a click outside closes it.
import QtQuick

Item {
    id: root
    property string title
    property string description
    default property alias content: body.data
    property alias footer: foot.data
    property Item initialFocus: null   // what has the keyboard when it opens
    signal closed()

    anchors.fill: parent
    z: 50
    visible: false
    function open() { visible = true; (initialFocus || root).forceActiveFocus() }
    function close() { visible = false; closed() }

    Keys.onEscapePressed: close()

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.5)
        MouseArea { anchors.fill: parent; onClicked: root.close() }
    }
    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 512)
        height: col.implicitHeight + 48
        radius: Theme.radius
        color: Theme.card
        border.width: 1
        border.color: Theme.border
        MouseArea { anchors.fill: parent }  // clicks inside stay inside
        Column {
            id: col
            x: 24; y: 24
            width: parent.width - 48
            spacing: 16
            Column {
                width: parent.width
                spacing: 8
                Text { textFormat: Text.PlainText;
                    width: parent.width
                    text: root.title
                    color: Theme.foreground
                    font.pixelSize: 18
                    font.weight: Font.Bold
                    wrapMode: Text.Wrap
                }
                Text { textFormat: Text.PlainText;
                    width: parent.width
                    visible: text !== ""
                    text: root.description
                    color: Theme.muted
                    font.pixelSize: Theme.fontSize
                    wrapMode: Text.Wrap
                }
            }
            Column { id: body; width: parent.width; spacing: 14 }
            Row {
                id: foot
                spacing: 8
                anchors.right: parent.right
            }
        }
        Btn {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            width: 28; height: 28
            kind: "ghost"; icon: "x"; tip: "Close"
            onClicked: root.close()
        }
    }
}
