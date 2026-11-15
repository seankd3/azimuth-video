// The playhead: a 2 px accent line with a cap at the top. position: the x of the time it marks.
import QtQuick
import QtQuick.Shapes

Item {
    id: head
    property real position: 0
    x: position - width / 2
    width: 10
    z: 3
    Rectangle { x: head.width / 2 - 1; width: 2; height: head.height; color: Theme.accent }
    Shape {
        width: 10; height: 8
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"; strokeWidth: 0; fillColor: Theme.accent
            PathSvg { path: "M0 0H10L5 8Z" }
        }
    }
}
