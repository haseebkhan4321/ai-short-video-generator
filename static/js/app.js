/* Shared front-end behaviour. No framework, no build step.
   Every block is defensive: pages that lack an element simply skip it. */
(function () {
  'use strict';

  /* ---- Mobile navigation drawer ---------------------------------------- */

  (function drawer() {
    var toggle = document.querySelector('[data-drawer-toggle]');
    var backdrop = document.querySelector('[data-drawer-backdrop]');
    if (!toggle) return;

    function set(open) {
      document.body.classList.toggle('nav-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    toggle.addEventListener('click', function () {
      set(!document.body.classList.contains('nav-open'));
    });
    if (backdrop) backdrop.addEventListener('click', function () { set(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') set(false);
    });
    // Following a link inside the drawer should close it behind you.
    document.querySelectorAll('.sidebar a').forEach(function (a) {
      a.addEventListener('click', function () { set(false); });
    });
  })();

  /* ---- Account switcher ------------------------------------------------ */

  // The target account id lives in the form action, so rewrite it from the
  // selected option and submit. Switching is a POST because it changes session
  // state, which is also why this is not just a link.
  (function switcher() {
    var select = document.querySelector('[data-account-switch]');
    if (!select) return;
    var form = select.closest('form');
    var base = form.getAttribute('data-switch-base');
    select.addEventListener('change', function () {
      form.action = base.replace(/\/0\/$/, '/' + select.value + '/');
      form.submit();
    });
  })();

  /* ---- Audio players --------------------------------------------------- */

  (function players() {
    var nodes = document.querySelectorAll('.player');
    if (!nodes.length) return;
    var RATES = [1, 1.25, 1.5, 1.75, 2];

    function fmt(seconds) {
      if (!isFinite(seconds) || seconds < 0) return '0:00';
      var s = Math.floor(seconds);
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var sec = String(s % 60).padStart(2, '0');
      return h ? h + ':' + String(m).padStart(2, '0') + ':' + sec : m + ':' + sec;
    }

    // SVG elements have no .hidden IDL property, so toggle display instead.
    function show(el, visible) {
      if (el) el.style.display = visible ? '' : 'none';
    }

    nodes.forEach(function (el) {
      var audio = el.querySelector('audio');
      var playBtn = el.querySelector('[data-play]');
      var iconPlay = el.querySelector('[data-icon-play]');
      var iconPause = el.querySelector('[data-icon-pause]');
      var time = el.querySelector('[data-time]');
      var seek = el.querySelector('[data-seek]');
      var rateBtn = el.querySelector('[data-rate]');
      var muteBtn = el.querySelector('[data-mute]');
      var iconVol = el.querySelector('[data-icon-vol]');
      var iconMuted = el.querySelector('[data-icon-muted]');
      var seeking = false;

      function render() {
        var dur = audio.duration;
        var cur = seeking && isFinite(dur) ? (seek.value / 1000) * dur : audio.currentTime;
        time.textContent = fmt(cur) + ' / ' + fmt(dur);
        if (!seeking) {
          seek.value = isFinite(dur) && dur ? Math.round((audio.currentTime / dur) * 1000) : 0;
        }
        var pct = seek.value / 10;
        seek.style.background =
          'linear-gradient(to right, var(--accent) ' + pct + '%, var(--surface-3) ' + pct + '%)';
      }

      playBtn.addEventListener('click', function () {
        if (audio.paused) audio.play(); else audio.pause();
      });
      audio.addEventListener('play', function () {
        show(iconPlay, false);
        show(iconPause, true);
        playBtn.setAttribute('aria-label', 'Pause');
        // One player at a time.
        document.querySelectorAll('.player audio').forEach(function (other) {
          if (other !== audio) other.pause();
        });
      });
      audio.addEventListener('pause', function () {
        show(iconPlay, true);
        show(iconPause, false);
        playBtn.setAttribute('aria-label', 'Play');
      });
      audio.addEventListener('loadedmetadata', render);
      audio.addEventListener('timeupdate', function () { if (!seeking) render(); });
      audio.addEventListener('ended', render);

      seek.addEventListener('input', function () { seeking = true; render(); });
      seek.addEventListener('change', function () {
        if (isFinite(audio.duration)) audio.currentTime = (seek.value / 1000) * audio.duration;
        seeking = false;
        render();
      });

      rateBtn.addEventListener('click', function () {
        var next = RATES[(RATES.indexOf(audio.playbackRate) + 1) % RATES.length] || 1;
        audio.playbackRate = next;
        rateBtn.textContent = next + '×';
      });

      muteBtn.addEventListener('click', function () { audio.muted = !audio.muted; });
      audio.addEventListener('volumechange', function () {
        show(iconVol, !audio.muted);
        show(iconMuted, audio.muted);
        muteBtn.setAttribute('aria-label', audio.muted ? 'Unmute' : 'Mute');
      });

      render();
    });
  })();

  /* ---- Text field affordances ------------------------------------------ */

  // Spellcheck and sentence capitalisation on free-text fields only. Password
  // and email inputs are excluded by the selector on purpose.
  (function textFields() {
    var sel = 'textarea, input[type="text"], input[type="search"], input:not([type])';
    document.querySelectorAll(sel).forEach(function (el) {
      el.setAttribute('spellcheck', 'true');
      el.setAttribute('autocorrect', 'on');
      el.setAttribute('autocapitalize', 'sentences');
    });
  })();

  /* ---- Glowing pointer ------------------------------------------------- */

  // A light that follows the cursor, plus a larger aura that lags behind it. The
  // lag is what reads as a trail rather than a sticker glued to the pointer.
  //
  // Built here rather than in the HTML so it simply does not exist on a device that
  // cannot use it: no fine pointer (touch), or reduced motion asked for. Both are
  // checked once, up front, because this runs on every frame the mouse moves.
  (function pointerGlow() {
    var fine = window.matchMedia('(hover: hover) and (pointer: fine)');
    var still = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (!fine.matches || still.matches) return;

    var dot = document.createElement('div');
    dot.className = 'pointer-glow';
    var aura = document.createElement('div');
    aura.className = 'pointer-aura';
    document.body.append(aura, dot);

    var target = { x: -300, y: -300 };
    var slow = { x: -300, y: -300 };
    var moved = false;
    var frame = null;

    function render() {
      // Ease the aura toward the cursor; the dot tracks it exactly.
      slow.x += (target.x - slow.x) * 0.12;
      slow.y += (target.y - slow.y) * 0.12;
      dot.style.transform = 'translate3d(' + target.x + 'px,' + target.y + 'px,0)';
      aura.style.transform = 'translate3d(' + slow.x + 'px,' + slow.y + 'px,0)';

      // Keep going only while the aura is still catching up, so an idle mouse costs
      // nothing.
      if (Math.abs(target.x - slow.x) > 0.4 || Math.abs(target.y - slow.y) > 0.4) {
        frame = requestAnimationFrame(render);
      } else {
        frame = null;
      }
    }

    function tick() {
      if (frame === null) frame = requestAnimationFrame(render);
    }

    document.addEventListener('mousemove', function (e) {
      target.x = e.clientX;
      target.y = e.clientY;
      if (!moved) {
        moved = true;
        // Start the aura where the cursor is, so it does not fly in from a corner.
        slow.x = target.x;
        slow.y = target.y;
        dot.classList.add('on');
        aura.classList.add('on');
      }
      // SVG and other non-HTML targets still implement closest(), but guard anyway
      // so a stray non-element target cannot throw on every frame.
      var over = e.target instanceof Element
        ? e.target.closest('a, button, [role="button"], summary, input, select, textarea')
        : null;
      dot.classList.toggle('hot', !!over);
      tick();
    }, { passive: true });

    // Fade out when the pointer leaves the window, so it does not sit frozen at the
    // edge of the page.
    document.addEventListener('mouseleave', function () {
      dot.classList.remove('on', 'hot');
      aura.classList.remove('on');
    });
    document.addEventListener('mouseenter', function () {
      if (moved) {
        dot.classList.add('on');
        aura.classList.add('on');
      }
    });
  })();

  /* ---- Destructive confirmations --------------------------------------- */

  (function confirmations() {
    document.querySelectorAll('[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
      });
    });
  })();
})();
