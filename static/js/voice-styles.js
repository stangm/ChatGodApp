/*
   Narrowing a style dropdown to what the selected voice can actually do.

   Shared by the control panel and the setup screen because they were written weeks
   apart and drifted: the panel narrowed its dropdown, /setup offered all thirty
   styles regardless of voice. The page said "Aria - 16 styles" and then listed
   thirty, and on /setup the wrong choice got *saved* as a character's default rather
   than being a mistake for one session.

   Why narrowing matters at all: Azure's response to an unsupported style is to
   render the line neutral and report nothing. There's no error to notice, so the
   only defence is not offering the combination.

   Usage: call VoiceStyles.init(map) once with {voiceName: [styles]}, then
   VoiceStyles.refresh(...) whenever the selected voice changes. Element ids are
   passed in rather than assumed, since the two pages name their controls
   differently.
*/

var VoiceStyles = (function () {
    var MAP = {};

    function init(map) {
        MAP = map || {};
    }

    function stylesFor(voiceName) {
        return MAP[voiceName] || [];
    }

    /*
       Rebuild one style dropdown.

       "random" is always offered and always first. For a voice with no styles it's
       the only option, and there it means "no express-as at all" rather than "pick
       one for me" -- same word, different meaning, which is worth knowing when
       reading the note this shows.

       preferred lets a caller force a value (the server telling us it reset one).
       Without it, whatever is currently selected is kept if the new voice supports
       it, so changing voice doesn't silently discard a deliberate choice.
    */
    function refresh(options) {
        var select = $(options.select);
        var available = stylesFor(options.voiceName);
        var current = options.preferred || select.val();

        select.empty().append($('<option>').val('random').text('random'));
        available.forEach(function (style) {
            select.append($('<option>').val(style).text(style));
        });

        var message = '';
        if (current !== 'random' && available.indexOf(current) === -1) {
            select.val('random');
            message = current + " isn't available on this voice - using random";
        } else {
            select.val(current);
            if (!available.length) message = 'this voice has no speaking styles';
        }

        if (options.note) {
            var el = $(options.note);
            el.text(message);
            el.toggleClass('visible', !!message);
        }
        return message;
    }

    return { init: init, refresh: refresh, stylesFor: stylesFor };
})();
