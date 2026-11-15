// A timecode, HH:MM:SS:FF at the given frame rate, in mono with tabular figures. faint: the "/ duration" beside it.
import QtQuick

Label {
    property real seconds: 0
    property real fps: 30
    property bool faint: false
    function format(t, rate) {
        const r = Math.max(1, Math.round(rate))
        const frames = Math.max(0, Math.floor(t * rate + 1e-6))
        const pad = n => (n < 10 ? "0" : "") + n
        const f = frames % r, s = Math.floor(frames / r)
        return pad(Math.floor(s / 3600)) + ":" + pad(Math.floor(s / 60) % 60) + ":" + pad(s % 60) + ":" + pad(f)
    }
    text: format(seconds, fps)
    textStyle: faint ? "label" : "code"
    color: faint ? Theme.text3 : Theme.text
    weight: faint ? 0 : Font.Medium
    elide: Text.ElideNone
}
