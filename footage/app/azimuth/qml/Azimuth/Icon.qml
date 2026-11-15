// One mark of the icon set (icons.json): 16-unit grid, stroke 1.4 scaled with the size, round caps and joins,
// filled only where the set says so.
import QtQuick
import QtQuick.Shapes

Item {
    id: icon
    property string name: ""
    property real size: 16
    property color color: Theme.text
    readonly property var def: Theme.icons[name] || null
    implicitWidth: size
    implicitHeight: size

    Shape {
        width: 16; height: 16
        scale: icon.size / 16
        transformOrigin: Item.TopLeft
        visible: !!icon.def
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            readonly property bool filled: !!icon.def && icon.def.fill
            strokeColor: filled ? "transparent" : icon.color
            strokeWidth: filled ? 0 : Theme.stroke
            fillColor: filled ? icon.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: icon.def ? icon.def.d : "" }
        }
    }
}
