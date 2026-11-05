import QtQuick
import Pulseboard

Window {
    id: win
    visible: true
    title: Reader.selected >= 0 ? Reader.selectedTitle + " — Pulseboard" : "Pulseboard"
    color: Theme.background

    ReaderPage {
        anchors.fill: parent
        visible: !Reader.managing
        onAskMarkAll: markAll.open()
    }
    Loader {
        anchors.fill: parent
        focus: true
        active: Reader.managing
        sourceComponent: ManagePage {
            focus: true
            Component.onCompleted: forceActiveFocus()
            onAskRemove: (f) => { remove.feed = f; remove.open() }
            onAskEdit: (f) => { edit.load(f); edit.open() }
            onAskImport: { opml.text = ""; importDlg.open() }
        }
    }

    // ---------------------------------------------------------------- dialogs

    Modal {
        id: markAll
        title: Reader.selected >= 0 ? "Mark this feed read?" : "Mark everything read?"
        Text { textFormat: Text.PlainText;
            visible: Reader.selected >= 0
            width: parent.width
            text: Reader.selectedTitle
            color: Theme.muted
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
        }
        footer: [
            Btn { text: "Cancel"; kind: "outline"; onClicked: markAll.close() },
            Btn { text: "Mark read"; onClicked: { markAll.close(); Reader.markAllRead() } }
        ]
        Keys.onReturnPressed: { markAll.close(); Reader.markAllRead() }
    }

    Modal {
        id: remove
        property int feed: -1
        title: "Remove feed?"
        Text { textFormat: Text.PlainText;
            width: parent.width
            text: "Stop following " + (remove.feed >= 0 ? Reader.feed(remove.feed).title || Reader.feed(remove.feed).url : "") + "?"
            color: Theme.muted
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
        }
        footer: [
            Btn { text: "Keep"; kind: "outline"; onClicked: remove.close() },
            Btn { text: "Remove"; kind: "destructive"; onClicked: { remove.close(); Reader.removeFeed(remove.feed) } }
        ]
    }

    Modal {
        id: edit
        property int feed: -1
        title: "Edit feed"
        function load(f) {
            feed = f
            const d = Reader.feed(f)
            editTitle.text = d.title
            editUrl.text = d.url
            editCat.text = d.category
        }
        function save() {
            if (editUrl.text.trim() === "") return
            edit.close()
            Reader.editFeed(feed, editTitle.text, editUrl.text, editCat.text)
        }
        initialFocus: editTitle.input
        LabeledField { id: editTitle; label: "Title"; placeholder: "Use the feed's own title"; onAccepted: edit.save() }
        LabeledField { id: editUrl; label: "Feed URL"; placeholder: "https://example.com/feed.xml"; onAccepted: edit.save() }
        LabeledField { id: editCat; label: "Category"; placeholder: "None"; onAccepted: edit.save() }
        footer: [
            Btn { text: "Cancel"; kind: "outline"; onClicked: edit.close() },
            Btn { text: "Save"; onClicked: edit.save() }
        ]
    }

    Modal {
        id: importDlg
        title: "Import OPML"
        description: "Paste your OPML here."
        initialFocus: opml
        Rectangle {
            width: parent.width
            height: 192
            radius: 8
            color: Theme.inputBg
            border.width: 1
            border.color: opml.activeFocus ? Theme.ring : Theme.inputBorder
            Flickable {
                id: opmlFlick
                anchors.fill: parent
                anchors.margins: 10
                clip: true
                contentHeight: opml.contentHeight
                boundsBehavior: Flickable.StopAtBounds
                TextEdit {
                    id: opml
                    width: opmlFlick.width
                    color: Theme.foreground
                    font.family: Theme.mono
                    font.pixelSize: 12
                    wrapMode: TextEdit.WrapAnywhere
                    selectByMouse: true
                    selectionColor: Theme.accent
                    onCursorRectangleChanged: {
                        if (cursorRectangle.y < opmlFlick.contentY) opmlFlick.contentY = cursorRectangle.y
                        else if (cursorRectangle.y + cursorRectangle.height > opmlFlick.contentY + opmlFlick.height)
                            opmlFlick.contentY = cursorRectangle.y + cursorRectangle.height - opmlFlick.height
                    }
                }
            }
        }
        footer: [
            Btn { text: "Cancel"; kind: "outline"; onClicked: importDlg.close() },
            Btn { text: "Import"; onClicked: { importDlg.close(); Reader.importOpml(opml.text) } }
        ]
    }

    // ---------------------------------------------------------------- toast

    Rectangle {
        id: toast
        z: 60
        visible: opacity > 0
        opacity: 0
        Behavior on opacity { NumberAnimation { duration: 150 } }
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: Math.min(toastText.implicitWidth + 32, win.width - 32)
        height: toastText.implicitHeight + 20
        radius: Theme.radius
        color: Theme.foreground
        Text { textFormat: Text.PlainText;
            id: toastText
            anchors.centerIn: parent
            width: Math.min(implicitWidth, win.width - 64)
            color: Theme.background
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
        }
        Timer { id: toastTimer; interval: 3500; onTriggered: toast.opacity = 0 }
        Connections {
            target: Reader
            function onToast(text) {
                toastText.text = text
                toast.opacity = 1
                toastTimer.restart()
            }
        }
    }
}
