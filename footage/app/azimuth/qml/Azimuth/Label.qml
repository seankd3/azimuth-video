// Text in one of the named text styles (tokens.toml [type]): wordmark, tag, title, menu, button, label, eyebrow,
// body, meta, heading, display, stat, code. Colour defaults to the theme's text. For the few parts the spec sets off
// a style (a key cap is code at 10.5 px), size (px), weight and caps (0 off, 1 on) adjust it; leave them for the
// style as it is. Don't set font.* on a Label: the style is one binding.
import QtQuick

Text {
    property string textStyle: "body"
    property real size: 0
    property int weight: 0
    property int caps: -1
    readonly property var style: Theme.type[textStyle] || Theme.type.body
    font: {
        const f = Theme.fonts[textStyle] || Theme.fonts.body
        if (!size && !weight && caps < 0) return f
        const px = size || style.size
        return Qt.font({ family: f.family, pointSize: f.pointSize * px / style.size, weight: weight || f.weight,
                         letterSpacing: style.tracking * px,
                         capitalization: caps < 0 ? f.capitalization : caps ? Font.AllUppercase : Font.MixedCase })
    }
    color: Theme.text
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
}
