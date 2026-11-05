// One article: source, age, title and preview; a click (left or middle) opens it
// in a new tab, and a right click gets the browser's own link menu.
import QtQuick
import Pulseboard

Item {
    id: root
    required property int index
    required property string feedTitle
    required property string title
    required property string preview
    required property string ago
    required property bool isRead
    required property bool newLine
    required property bool hasLink
    required property string url

    width: ListView.view ? ListView.view.width : 0
    height: line.height + content.height + 37

    Rectangle {
        id: line   // "new since the last fetch" goes above this row
        width: parent.width
        height: root.newLine ? 2 : 0
        color: Theme.destructive
    }
    Rectangle {
        anchors.fill: parent
        anchors.topMargin: line.height
        color: area.containsMouse ? Theme.hover : "transparent"
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onClicked: Reader.open(root.index)
        onContainsMouseChanged: Reader.hoverLink(containsMouse && root.hasLink ? root.url : "")
        Component.onDestruction: if (containsMouse) Reader.hoverLink("")
    }
    Column {
        id: content
        x: root.width < 860 ? 16 : 20
        y: line.height + 18
        width: toggleBtn.x - x - 10
        spacing: 0
        Row {
            width: parent.width
            spacing: 7
            Rectangle {
                width: 7; height: 7; radius: 3.5
                anchors.verticalCenter: parent.verticalCenter
                color: root.isRead ? Theme.border : Theme.accent
            }
            Text { textFormat: Text.PlainText;
                width: parent.width - 14 - agoText.width - 12
                text: root.feedTitle
                color: Theme.muted
                font.pixelSize: 12
                font.letterSpacing: 0.25
                elide: Text.ElideRight
            }
            Text { textFormat: Text.PlainText;
                id: agoText
                text: root.ago
                color: Theme.muted
                font.pixelSize: 12
                leftPadding: 5
            }
        }
        Text { textFormat: Text.PlainText;
            width: parent.width
            topPadding: 10
            text: root.title !== "" ? root.title : "(untitled)"
            color: Theme.foreground
            opacity: root.isRead ? 0.55 : 1
            font.pixelSize: 16
            font.weight: root.isRead ? Font.Normal : Font.Bold
            lineHeight: 1.2
            wrapMode: Text.Wrap
            maximumLineCount: 3
            elide: Text.ElideRight
        }
        Text { textFormat: Text.PlainText;
            width: parent.width
            visible: root.preview !== ""
            topPadding: 9
            text: root.preview
            color: Theme.muted
            opacity: root.isRead ? 0.78 : 1
            font.pixelSize: Theme.fontSize
            lineHeight: 1.3
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
    Btn {
        id: toggleBtn
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: line.height / 2
        kind: "ghost"
        icon: root.isRead ? "unread" : "check"
        tip: root.isRead ? "Mark unread" : "Mark read"
        onClicked: Reader.toggleRead(root.index)
    }
    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.border
    }
}
