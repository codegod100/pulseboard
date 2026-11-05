// Mouse-wheel and trackpad scrolling for a Flickable (declare it inside one,
// with `flick` set to it: a handler there lands on its contentItem).
// Flickable's own wheel handling turns each event into a slow, decelerating
// flick, which feels sluggish in the browser; this moves the content the
// distance the browser reports instead (a wheel notch is `step` pixels).
import QtQuick

WheelHandler {
    id: wheel
    required property Flickable flick
    property real step: 120     // pixels per wheel notch
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    orientation: Qt.Vertical

    // Where a run of notches is heading, so quick notches add up while animating.
    property real goal: 0

    function clamp(y) {
        const top = flick.originY - flick.topMargin
        const bottom = flick.originY + flick.contentHeight + flick.bottomMargin - flick.height
        return Math.max(top, Math.min(Math.max(top, bottom), y))
    }

    onWheel: (ev) => {
        if (flick.contentHeight <= flick.height) return
        flick.cancelFlick()
        if (ev.pixelDelta.y !== 0 && !anim.running) {
            // Trackpad: follow the fingers 1:1.
            flick.contentY = clamp(flick.contentY - ev.pixelDelta.y)
        } else {
            const dy = ev.pixelDelta.y !== 0 ? ev.pixelDelta.y : ev.angleDelta.y / 120 * step
            goal = clamp((anim.running ? goal : flick.contentY) - dy)
            anim.restart()
        }
        flick.returnToBounds()
    }

    property NumberAnimation anim: NumberAnimation {
        target: wheel.flick
        property: "contentY"
        to: wheel.goal
        duration: 140
        easing.type: Easing.OutCubic
    }
}
