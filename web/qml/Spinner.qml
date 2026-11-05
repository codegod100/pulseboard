import QtQuick
import QtQuick.Shapes

Item {
    implicitWidth: 24
    implicitHeight: 24
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "transparent"
        border.width: 2.5
        border.color: Theme.border
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Theme.accent
            strokeWidth: 2.5
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathAngleArc {
                centerX: 12; centerY: 12
                radiusX: 10.75; radiusY: 10.75
                startAngle: -135; sweepAngle: 90
            }
        }
        RotationAnimator on rotation { from: 0; to: 360; duration: 800; loops: Animation.Infinite; running: true }
    }
}
