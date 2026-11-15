// Photo's slider, for every app: 2 px line-strong track, 12 px thumb in the text colour, filled in text-2 from the
// rest value, a notch at rest. Double-click resets to rest. Arrows step, Shift x10, PageUp/PageDown x10, Home/End.
// The value label sits above at the end and is editable on click. Optional gradient track (temperature, hue).
import QtQuick
import QtQuick.Templates as T

Item {
    id: s
    property string label: ""
    property real from: 0
    property real to: 100
    property real value: 0
    property real rest: from
    property real stepSize: 1
    property int decimals: 0
    property string format: "{}"          // the value label: "{} K", "{} EV"
    property bool signed: false           // a + before values above zero
    property var gradient: null           // a list of colours along the track, or null
    signal moved()                        // the person changed the value (drag, keys, reset, typing)
    readonly property alias pressed: track.pressed
    readonly property alias visualFocus: track.visualFocus

    implicitWidth: 220
    implicitHeight: head.height + 4 + track.height
    opacity: enabled ? 1 : 0.4

    function clamp(v) { return Math.min(to, Math.max(from, v)) }
    function set(v) {
        v = clamp(Math.round((v - from) / stepSize) * stepSize + from)
        v = Number(v.toFixed(Math.max(decimals, 6)))
        if (v !== value) { value = v; moved() }
    }
    function shown(v) {
        const t = Math.abs(v).toFixed(decimals)
        const sign = v < 0 && Number(t) !== 0 ? "−" : (signed && v > 0 && Number(t) !== 0 ? "+" : "")
        return format.replace("{}", sign + t)
    }
    function at(v) { return to === from ? 0 : (clamp(v) - from) / (to - from) }

    Item {
        id: head
        width: parent.width
        height: Math.max(name.implicitHeight, readout.implicitHeight)
        Label { id: name; textStyle: "label"; text: s.label; color: Theme.text2; width: parent.width - readout.width - 8 }
        Label {
            id: readout
            anchors.right: parent.right
            textStyle: "code"; text: s.shown(s.value); visible: !edit.visible
            MouseArea { anchors.fill: parent; cursorShape: Qt.IBeamCursor; onClicked: { edit.text = s.value.toFixed(s.decimals); edit.visible = true; edit.forceActiveFocus(); edit.selectAll() } }
        }
        TextInput {
            id: edit
            visible: false
            anchors.right: parent.right
            width: Math.max(48, contentWidth + 4)
            horizontalAlignment: TextInput.AlignRight
            font: Theme.fonts.code
            color: Theme.text
            selectionColor: Theme.selection
            selectedTextColor: Theme.text
            validator: DoubleValidator {}
            onAccepted: { s.set(Number(text.replace("−", "-"))); visible = false }
            onActiveFocusChanged: if (!activeFocus) visible = false
            Keys.onEscapePressed: visible = false
            Rectangle { anchors.fill: parent; anchors.margins: -2; z: -1; color: Theme.well; radius: Theme.radius.control
                        border.width: 1; border.color: Theme.lineStrong }
        }
    }

    T.Slider {
        id: track
        y: head.height + 4
        width: parent.width
        height: 16
        from: s.from; to: s.to; value: s.value; stepSize: s.stepSize
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        property double lastPress: 0
        onMoved: s.set(value)
        onPressedChanged: {
            if (!pressed) return
            const now = Date.now()
            if (now - lastPress < Qt.styleHints.mouseDoubleClickInterval) { s.set(s.rest); lastPress = 0 }
            else lastPress = now
        }
        Keys.onPressed: e => {
            const big = (e.modifiers & Qt.ShiftModifier) ? 10 : 1
            const k = e.key
            if (k === Qt.Key_Left || k === Qt.Key_Down) s.set(s.value - s.stepSize * big)
            else if (k === Qt.Key_Right || k === Qt.Key_Up) s.set(s.value + s.stepSize * big)
            else if (k === Qt.Key_PageDown) s.set(s.value - s.stepSize * 10)
            else if (k === Qt.Key_PageUp) s.set(s.value + s.stepSize * 10)
            else if (k === Qt.Key_Home) s.set(s.from)
            else if (k === Qt.Key_End) s.set(s.to)
            else return
            e.accepted = true
        }

        background: Item {
            Rectangle {                              // the track
                visible: !s.gradient
                y: (track.height - height) / 2
                width: parent.width; height: 2; radius: 1
                color: Theme.lineStrong
            }
            Row {                                    // or a gradient: temperature, tint, hue
                visible: !!s.gradient
                y: (track.height - height) / 2
                height: 2
                Repeater {
                    model: s.gradient ? s.gradient.length - 1 : 0
                    Rectangle {
                        required property int index
                        width: track.width / Math.max(1, s.gradient.length - 1); height: 2
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: s.gradient[index] }
                            GradientStop { position: 1; color: s.gradient[index + 1] }
                        }
                    }
                }
            }
            Rectangle {                              // the fill, from rest to the value
                readonly property real a: s.at(s.rest) * track.width
                readonly property real b: track.visualPosition * track.width
                visible: !s.gradient
                x: Math.min(a, b); width: Math.abs(b - a)
                y: (track.height - height) / 2; height: 2; radius: 1
                color: Theme.text2
            }
            Rectangle {                              // the notch at rest
                visible: s.rest > s.from && s.rest < s.to
                x: Math.round(s.at(s.rest) * track.width) - 0.5
                y: (track.height - height) / 2
                width: 1; height: 8
                color: Theme.text3
            }
        }
        handle: Rectangle {
            x: track.visualPosition * track.width - width / 2
            y: (track.height - height) / 2
            width: 12; height: 12; radius: 6
            color: Theme.text
            border.width: 2
            border.color: Theme.panel
            scale: track.hovered || track.pressed ? 1.15 : 1
            Behavior on scale { NumberAnimation { duration: Theme.motion.fast } }
            Rectangle {                              // keyboard focus: a ring round the thumb
                anchors.centerIn: parent
                width: 18; height: 18; radius: 9
                color: "transparent"; border.width: 2; border.color: Theme.focus
                visible: track.visualFocus
            }
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }
}
