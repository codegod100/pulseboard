// Manage feeds: add, pick, edit and remove subscriptions; OPML in and out.
import QtQuick
import Pulseboard

Item {
    id: page
    signal askRemove(int feed)
    signal askEdit(int feed)
    signal askImport()

    Rectangle {  // top bar
        id: topbar
        width: parent.width
        height: 56
        color: "transparent"
        Btn {
            id: back
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            kind: "ghost"; icon: "back"; tip: "Back"
            onClicked: Reader.closeManage()
        }
        Text { textFormat: Text.PlainText;
            anchors.left: back.right
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: "Manage feeds"
            color: Theme.foreground
            font.pixelSize: 18
            font.weight: Font.Bold
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
    }
    Keys.onEscapePressed: Reader.closeManage()

    ListView {
        id: list
        anchors.top: topbar.bottom
        anchors.bottom: parent.bottom
        width: parent.width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: Reader.feedFilter
        WheelScroll { flick: list }
        readonly property real colWidth: Math.min(760, width) - 32
        readonly property real colX: (width - Math.min(760, width)) / 2 + 16

        header: Column {
            x: list.colX
            width: list.colWidth
            topPadding: 16
            spacing: 8
            Heading { text: "Add a subscription" }
            Row {
                width: parent.width
                spacing: 8
                Field {
                    id: addField
                    width: parent.width - 8 - addBtn.width
                    placeholder: "https://example.com/feed.xml"
                    inputHints: Qt.ImhUrlCharactersOnly | Qt.ImhNoAutoUppercase
                    onAccepted: Reader.addFeed(text)
                    Connections { target: Reader; function onAddSucceeded() { addField.text = "" } }
                }
                Item {
                    width: addBtn.width
                    height: 36
                    Btn {
                        id: addBtn
                        visible: !Reader.adding
                        icon: "plus"; text: "Add"
                        onClicked: Reader.addFeed(addField.text)
                    }
                    Spinner { visible: Reader.adding; anchors.centerIn: parent }
                }
            }
            Item { width: 1; height: 20 }
            Item {
                width: parent.width
                height: 24
                Heading { text: "Subscriptions"; anchors.bottom: parent.bottom }
                Text { textFormat: Text.PlainText;
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    text: Reader.feedCount
                    color: Theme.muted
                    font.pixelSize: Theme.fontSize
                }
            }
            Field {
                width: parent.width
                placeholder: "Filter feeds"
                onTextChanged: Reader.feedFilter.text = text
            }
            Item { width: 1; height: 0 }
        }

        delegate: Item {
            id: row
            required property int index
            required property int feedIndex
            required property string title
            required property string feedUrl
            required property string error
            required property int unread
            required property string initial
            required property string faviconUrl
            width: list.width
            height: Math.max(52, text.implicitHeight + 16)

            Rectangle {  // the card the rows sit in
                x: list.colX
                width: list.colWidth
                y: row.index === 0 ? 0 : -1   // share the border with the row above
                height: parent.height - y
                color: Theme.card
                border.width: 1
                border.color: Theme.border
            }
            Row {
                x: list.colX + 12
                width: list.colWidth - 18
                height: parent.height
                spacing: 10
                Rectangle {  // favicon, with the title's initial underneath
                    width: 18; height: 18; radius: 3
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.muted
                    clip: true
                    Text { textFormat: Text.PlainText; anchors.centerIn: parent; text: row.initial; color: Theme.background; font.pixelSize: 11; font.weight: Font.Bold }
                    Image {
                        anchors.fill: parent
                        source: row.faviconUrl
                        visible: status === Image.Ready
                        sourceSize: Qt.size(36, 36)
                        asynchronous: true
                        Rectangle { anchors.fill: parent; color: Theme.background; z: -1 }
                    }
                }
                Column {
                    id: text
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 28 - (unreadText.visible ? unreadText.width + 10 : 0) - 2 * 46
                    Text { textFormat: Text.PlainText;  // the title opens the feed's articles: this is how a feed gets picked
                        width: Math.min(implicitWidth, parent.width)
                        text: row.title
                        color: Theme.foreground
                        font.pixelSize: Theme.fontSize
                        font.weight: Font.Bold
                        font.underline: pick.containsMouse
                        elide: Text.ElideRight
                        MouseArea {
                            id: pick
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Reader.select(row.feedIndex)
                        }
                    }
                    Text { textFormat: Text.PlainText; width: parent.width; text: row.feedUrl; color: Theme.muted; font.pixelSize: 12; elide: Text.ElideRight }
                    Text { textFormat: Text.PlainText;  // the last fetch failed: say why, or the feed just looks empty
                        width: parent.width
                        visible: row.error !== ""
                        text: row.error
                        color: Theme.destructive
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }
                Text { textFormat: Text.PlainText;
                    id: unreadText
                    visible: row.unread > 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.unread + " unread"
                    color: Theme.muted
                    font.pixelSize: 12
                }
                Btn {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "ghost"; icon: "pencil"; tip: "Edit feed"
                    onClicked: page.askEdit(row.feedIndex)
                }
                Btn {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "ghost"; icon: "trash"; tip: "Remove feed"
                    tint: Theme.destructive
                    onClicked: page.askRemove(row.feedIndex)
                }
            }
        }

        footer: Column {
            x: list.colX
            width: list.colWidth
            spacing: 8
            bottomPadding: 24
            Text { textFormat: Text.PlainText;
                visible: list.count === 0
                width: parent.width
                topPadding: 32
                bottomPadding: 32
                horizontalAlignment: Text.AlignHCenter
                text: Reader.feedFilter.text !== "" ? "No matching feeds." : "No subscriptions yet."
                color: Theme.muted
                font.pixelSize: 13
            }
            Item { width: 1; height: 20 }
            Heading { text: "Backup & restore" }
            Flow {
                width: parent.width
                spacing: 8
                Btn { kind: "outline"; icon: "upload"; text: "Import OPML"; onClicked: page.askImport() }
                Btn { kind: "outline"; icon: "copy"; text: "Copy OPML backup"; onClicked: Reader.exportOpml() }
            }
        }
    }
    ScrollBar { flick: list; anchors.top: undefined; y: list.y + list.visibleArea.yPosition * list.height }
}
