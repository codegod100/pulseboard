// A button: "primary" (filled), "outline", "ghost" or "destructive"; with an
// icon, text, or both. An icon-only button is square.
import QtQuick

Rectangle {
    id: root
    property string text
    property string icon
    property string kind: "primary"
    property string tip          // shown as a tooltip-ish title for icon buttons
    property bool enabled: true
    property bool spinning: false
    property color tint: "transparent"   // overrides the icon/text colour
    signal clicked()

    readonly property bool iconOnly: text === ""
    readonly property color ink: tint.a > 0 ? tint
                               : kind === "primary" ? Theme.primaryInk
                               : kind === "destructive" ? "#ffffff"
                               : kind === "ghost" && iconOnly ? (area.containsMouse ? Theme.foreground : Theme.muted)
                               : Theme.foreground

    implicitHeight: 36
    implicitWidth: iconOnly ? 36 : row.implicitWidth + 32
    radius: 8
    opacity: enabled ? 1 : 0.5
    color: kind === "primary" ? (area.containsMouse ? Qt.darker(Theme.primary, Theme.dark ? 1.1 : 0.8) : Theme.primary)
         : kind === "destructive" ? (area.containsMouse ? Qt.darker(Theme.destructive, 1.1) : Theme.destructive)
         : area.containsMouse ? Theme.secondary
         : kind === "outline" ? Theme.card : "transparent"
    border.width: kind === "outline" ? 1 : 0
    border.color: Theme.inputBorder
    activeFocusOnTab: true

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Icon {
            id: ic
            visible: root.icon !== ""
            name: root.icon
            color: root.ink
            anchors.verticalCenter: parent.verticalCenter
            RotationAnimator on rotation {
                running: root.spinning
                from: 0; to: 360; duration: 800
                loops: Animation.Infinite
                onRunningChanged: if (!running) ic.rotation = 0
            }
        }
        Text { textFormat: Text.PlainText;
            visible: !root.iconOnly
            text: root.text
            color: root.ink
            font.pixelSize: Theme.fontSize
            font.weight: Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    Rectangle {  // focus ring
        anchors.fill: parent
        anchors.margins: -3
        radius: parent.radius + 3
        color: "transparent"
        border.width: 2
        border.color: Theme.ring
        visible: root.activeFocus
        opacity: 0.6
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        enabled: root.enabled
        onClicked: root.clicked()
    }
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onSpacePressed: if (enabled) clicked()

    // a native-looking hint for icon buttons
    Rectangle {
        visible: root.iconOnly && root.tip !== "" && area.containsMouse && hintDelay.done
        z: 100
        anchors.top: parent.bottom
        anchors.topMargin: 6
        anchors.horizontalCenter: parent.horizontalCenter
        width: hint.implicitWidth + 14
        height: hint.implicitHeight + 8
        radius: 6
        color: Theme.foreground
        Text { textFormat: Text.PlainText; id: hint; anchors.centerIn: parent; text: root.tip; color: Theme.background; font.pixelSize: 12 }
    }
    Timer {
        id: hintDelay
        property bool done: false
        interval: 600
        running: area.containsMouse
        onTriggered: done = true
        onRunningChanged: if (!running) done = false
    }
}
