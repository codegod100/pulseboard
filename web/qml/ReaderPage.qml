// The article list: top bar, search and status tabs, then the rows.
import QtQuick
import Pulseboard

Item {
    id: page
    signal askMarkAll()
    readonly property bool narrow: width < 860

    Rectangle {  // top bar
        id: topbar
        width: parent.width
        height: 56
        color: "transparent"
        Row {
            x: 16
            height: parent.height
            spacing: 8
            width: actions.x - x - 8
            Text { textFormat: Text.PlainText;
                id: heading
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, parent.width - countBadge.width - (clearSel.visible ? 44 : 0) - 8)
                text: Reader.selected >= 0 ? Reader.selectedTitle : "Pulseboard"
                color: Theme.foreground
                font.pixelSize: 18
                font.weight: Font.Bold
                elide: Text.ElideRight
            }
            Rectangle {  // unread count for what is shown
                id: countBadge
                readonly property int n: Reader.selected >= 0 ? Reader.selectedUnread : Reader.unread
                visible: n > 0
                anchors.verticalCenter: parent.verticalCenter
                width: visible ? countText.implicitWidth + 12 : 0
                height: 18
                radius: 6
                color: Reader.selected >= 0 ? Theme.accent : Theme.secondary
                Text { textFormat: Text.PlainText;
                    id: countText
                    anchors.centerIn: parent
                    text: countBadge.n
                    color: Reader.selected >= 0 ? Theme.accentInk : Theme.muted
                    font.pixelSize: 12
                    font.weight: Font.Bold
                }
            }
            Btn {  // feeds are picked in Manage feeds; this goes back to all of them
                id: clearSel
                visible: Reader.selected >= 0
                anchors.verticalCenter: parent.verticalCenter
                kind: "ghost"; icon: "x"; tip: "Show all feeds"
                onClicked: Reader.select(-1)
            }
        }
        Row {
            id: actions
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Btn { kind: "ghost"; icon: "rss"; tip: "Manage feeds"; onClicked: Reader.openManage() }
            Btn { kind: "ghost"; icon: "check-all"; tip: "Mark all read"; onClicked: page.askMarkAll() }
            Btn { kind: "ghost"; icon: "refresh"; tip: "Refresh"; spinning: Reader.refreshing; onClicked: Reader.refresh() }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
    }

    Text { textFormat: Text.PlainText;
        id: feedsError
        anchors.top: topbar.bottom
        x: 16
        width: parent.width - 32
        height: text === "" ? 0 : implicitHeight + 8
        topPadding: text === "" ? 0 : 8
        text: Reader.feedsError
        color: Theme.destructive
        font.pixelSize: 13
        wrapMode: Text.Wrap
    }

    Flow {  // search, and the status filter (meaningless during a search)
        id: toolbar
        anchors.top: feedsError.bottom
        anchors.topMargin: 12
        x: 16
        width: parent.width - 32
        spacing: 8
        Field {
            id: search
            width: page.narrow || Reader.search !== "" ? toolbar.width
                 : toolbar.width - tabs.width - 8
            placeholder: "Search articles"
            leftPad: 34
            rightPad: Reader.search !== "" ? 40 : 12
            inputHints: Qt.ImhNoPredictiveText
            onAccepted: Reader.applySearch(text)
            onEscaped: { text = ""; Reader.clearSearch() }
            Icon { name: "search"; color: Theme.muted; x: 10; anchors.verticalCenter: parent.verticalCenter }
            Btn {
                visible: Reader.search !== ""
                anchors.right: parent.right
                anchors.rightMargin: 2
                anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32
                kind: "ghost"; icon: "x"; tip: "Clear search"
                onClicked: { search.text = ""; Reader.clearSearch() }
            }
            Connections {
                target: Reader
                function onSearchReset() { search.text = "" }  // picking a feed drops the search
            }
        }
        Tabs {
            id: tabs
            visible: Reader.search === ""
            labels: ["Unread", "All", "Read"]
            current: Reader.status
            onPicked: (i) => Reader.setStatus(i)
        }
    }

    Item {
        id: body
        anchors.top: toolbar.bottom
        anchors.topMargin: 12
        anchors.bottom: parent.bottom
        width: parent.width

        Column {  // failed
            visible: Reader.listState === Reader.Failed
            anchors.centerIn: parent
            width: Math.min(parent.width - 64, 480)
            spacing: 8
            Text { textFormat: Text.PlainText; anchors.horizontalCenter: parent.horizontalCenter; text: "!"; color: Theme.destructive; font.pixelSize: 40; font.weight: Font.Bold }
            Text { textFormat: Text.PlainText; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: Reader.listError; color: Theme.foreground; font.pixelSize: Theme.fontSize; wrapMode: Text.Wrap }
            Btn { anchors.horizontalCenter: parent.horizontalCenter; text: "Retry"; kind: "outline"; onClicked: Reader.retry() }
        }
        Spinner {
            visible: Reader.listState === Reader.Loading && list.count === 0
            anchors.centerIn: parent
        }
        Text { textFormat: Text.PlainText;
            visible: Reader.listState === Reader.Ready && list.count === 0
            anchors.centerIn: parent
            width: parent.width - 64
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: Reader.search !== "" ? "Nothing matches “" + Reader.search + "”." : "Nothing here."
            color: Theme.muted
            font.pixelSize: Theme.fontSize
        }

        Rectangle { width: parent.width; height: 1; color: Theme.border; visible: list.count > 0 }
        ListView {
            id: list
            visible: Reader.listState !== Reader.Failed && count > 0
            anchors.fill: parent
            anchors.topMargin: 1
            clip: true
            model: Reader.articles
            opacity: Reader.listState === Reader.Loading ? 0.6 : 1
            Behavior on opacity { NumberAnimation { duration: 200 } }
            boundsBehavior: Flickable.StopAtBounds
            delegate: ArticleRow {}
            Connections {
                target: Reader.articles
                function onModelReset() { list.positionViewAtBeginning() }
            }
        }
        ScrollBar { flick: list; visible: list.visible && ratio < 1 }
    }
}
