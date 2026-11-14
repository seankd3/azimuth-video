// One shot playing: its source file, drawn through its framing (geometry from the backend) and printed through its
// LUT. The window holds two decks: one plays while the other waits on the next shot, so a cut doesn't wait to load.
import QtQuick
import QtMultimedia

Item {
    id: deck
    property var shot: null            // an entry of backend.shots
    property var geometry: shot ? shot.geometry : null
    property string look: ""
    property bool graded: true
    property real vignette: 0           // the look's vignette in stops, 0 in the frame editor
    property real flat: 0.5
    property real unit: width           // the edit's window width in pixels: the geometry's unit
    property bool whole: false          // the frame editor: the whole turned frame centred, not the window
    readonly property alias player: player
    readonly property real sourceTime: player.position / 1000
    // Played out: past the shot's last frame, or at the end of its file.
    readonly property bool ended: !!shot && (player.mediaStatus === MediaPlayer.EndOfMedia
                                             || player.position >= (shot.start + shot.duration) * 1000 - 500 / shot.fps)
    property real pending: -1           // a seek asked for while the file loads: made once it has loaded

    function cue(s, t) {
        shot = s
        if (!s || !s.path) return
        const url = "file://" + s.path
        if (player.source.toString() !== url) player.source = url
        pending = Math.round(t * 1000)
        if (player.mediaStatus === MediaPlayer.LoadedMedia || player.mediaStatus === MediaPlayer.BufferedMedia
                || player.mediaStatus === MediaPlayer.EndOfMedia) seekPending()
        if (player.playbackState !== MediaPlayer.PlayingState) player.pause()
    }
    function seekPending() { if (pending >= 0) { player.position = pending; pending = -1 } }

    MediaPlayer {
        id: player
        videoOutput: video
        audioOutput: AudioOutput {}
        onMediaStatusChanged: if (mediaStatus === MediaPlayer.LoadedMedia || mediaStatus === MediaPlayer.BufferedMedia) deck.seekPending()
    }

    Item {
        id: picture
        anchors.fill: parent
        visible: !!deck.geometry && !!deck.geometry.width
        layer.enabled: deck.graded
        layer.format: ShaderEffectSource.RGBA16F
        layer.effect: ShaderEffect {
            property var lut: Image {
                source: deck.shot && deck.shot.path ? "image://av/lut/" + deck.look + "/" + encodeURIComponent(deck.shot.path) : ""
                smooth: true
                visible: false
            }
            property real vignette: deck.vignette
            property real untouched: deck.flat
            property real squeeze: deck.shot && deck.shot.oval ? deck.shot.oval : 1
            property real aspect: deck.width / Math.max(deck.height, 1)
            property real graded: deck.graded && deck.shot && deck.shot.graded && lut.status === Image.Ready ? 1 : 0
            fragmentShader: lutShader
        }

        VideoOutput {
            id: video
            fillMode: VideoOutput.Stretch
            width: deck.geometry ? deck.geometry.width * deck.unit : 0
            height: deck.geometry ? deck.geometry.height * deck.unit : 0
            x: deck.width / 2 + (deck.geometry && !deck.whole ? deck.geometry.x * deck.unit : 0) - width / 2
            y: deck.height / 2 + (deck.geometry && !deck.whole ? deck.geometry.y * deck.unit : 0) - height / 2
            rotation: deck.geometry ? deck.geometry.rotation : 0
        }
    }
}
