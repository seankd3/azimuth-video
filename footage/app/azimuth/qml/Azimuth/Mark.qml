// The compass mark (mark.svg): a faint ring and ticks, the needle in the accent.
import QtQuick
import QtQuick.Shapes

Item {
    id: mark
    property real size: 24
    property color color: Theme.text3
    property color needle: Theme.accent
    implicitWidth: size
    implicitHeight: size

    Shape {
        width: Theme.mark.size; height: Theme.mark.size
        scale: mark.size / Theme.mark.size
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Theme.alpha(mark.color, 0.5); strokeWidth: Theme.mark.stroke; fillColor: "transparent"
            PathSvg { path: Theme.mark.ring + " " + Theme.mark.ticks }
        }
        ShapePath {
            strokeColor: "transparent"; strokeWidth: 0; fillColor: mark.needle
            PathSvg { path: Theme.mark.needle }
        }
    }
}
