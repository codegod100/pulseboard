// A one-line text input with a placeholder.
import QtQuick

Rectangle {
    id: root
    property alias text: input.text
    property string placeholder
    property alias input: input
    property int leftPad: 12
    property int rightPad: 12
    property int inputHints: Qt.ImhNone
    signal accepted()
    signal escaped()

    implicitHeight: 36
    implicitWidth: 200
    radius: 8
    color: Theme.inputBg
    border.width: 1
    border.color: input.activeFocus ? Theme.ring : Theme.inputBorder

    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: root.leftPad
        anchors.rightMargin: root.rightPad
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.foreground
        selectionColor: Theme.accent
        selectedTextColor: Theme.accentInk
        font.pixelSize: Theme.fontSize
        clip: true
        selectByMouse: true
        inputMethodHints: root.inputHints
        onAccepted: root.accepted()
        Keys.onEscapePressed: (e) => { e.accepted = false; root.escaped() }  // a dialog still closes
    }
    Text { textFormat: Text.PlainText;
        anchors.fill: input
        verticalAlignment: Text.AlignVCenter
        text: root.placeholder
        color: Theme.muted
        font.pixelSize: Theme.fontSize
        elide: Text.ElideRight
        visible: input.text === "" && !input.preeditText
    }
    MouseArea {  // a click anywhere in the box focuses it
        anchors.fill: parent
        cursorShape: Qt.IBeamCursor
        acceptedButtons: Qt.NoButton
    }
}
