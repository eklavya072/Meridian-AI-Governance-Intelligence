import { useRef, useEffect, useState } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText as GSAPSplitText } from 'gsap/SplitText';
import { useGSAP } from '@gsap/react';

gsap.registerPlugin(ScrollTrigger, GSAPSplitText, useGSAP);

const SplitText = ({
  text,
  className = '',
  delay = 50,
  duration = 1.25,
  ease = 'power3.out',
  splitType = 'chars',
  from = { opacity: 0, y: 40 },
  to = { opacity: 1, y: 0 },
  threshold = 0.1,
  rootMargin = '-100px',
  textAlign = 'center',
  tag = 'p',
  onLetterAnimationComplete = () => {},
  /* playOnMount: run the animation immediately when the element mounts,
     instead of waiting for a ScrollTrigger pass. For headings that are
     already in view at page open (e.g. a page title), scroll-triggering
     adds a visible delay — the user sees the plain text first, then the
     effect. This mode skips both the ScrollTrigger and the
     document.fonts gate so the letters animate the instant the page
     renders. */
  playOnMount = false
}) => {
  const ref = useRef(null);
  const animationCompletedRef = useRef(false);
  const onCompleteRef = useRef(onLetterAnimationComplete);
  const [fontsLoaded, setFontsLoaded] = useState(false);

  // Keep callback ref updated
  useEffect(() => {
    onCompleteRef.current = onLetterAnimationComplete;
  }, [onLetterAnimationComplete]);

  useEffect(() => {
    /* playOnMount: the effect runs immediately on mount, so waiting on
       document.fonts is pointless AND harmful — when the promise resolves
       it flips fontsLoaded, re-rendering the tag. That re-render would
       replace GSAP's split chars with the plain text node (React doesn't
       know about the DOM GSAP inserted), so the heading would flash as
       plain text, then re-split. Skip the subscription entirely. */
    if (playOnMount) return;
    if (document.fonts.status === 'loaded') {
      setFontsLoaded(true);
    } else {
      document.fonts.ready.then(() => {
        setFontsLoaded(true);
      });
    }
  }, [playOnMount]);

  useGSAP(
    () => {
      if (!ref.current || !text) return;
      // playOnMount skips the fonts gate (see prop comment); the
      // scroll-triggered path still waits for fonts to avoid splitting
      // before the webfont measures correctly.
      if (!playOnMount && !fontsLoaded) return;
      // Prevent re-animation if already completed
      if (animationCompletedRef.current) return;
      const el = ref.current;

      if (el._rbsplitInstance) {
        try {
          el._rbsplitInstance.revert();
        } catch (_) {
          /* noop */
        }
        el._rbsplitInstance = null;
      }

      const startPct = (1 - threshold) * 100;
      const marginMatch = /^(-?\d+(?:\.\d+)?)(px|em|rem|%)?$/.exec(rootMargin);
      const marginValue = marginMatch ? parseFloat(marginMatch[1]) : 0;
      const marginUnit = marginMatch ? marginMatch[2] || 'px' : 'px';
      const sign =
        marginValue === 0
          ? ''
          : marginValue < 0
            ? `-=${Math.abs(marginValue)}${marginUnit}`
            : `+=${marginValue}${marginUnit}`;
      const start = `top ${startPct}%${sign}`;

      let targets;
      const assignTargets = self => {
        if (splitType.includes('chars') && self.chars.length) targets = self.chars;
        if (!targets && splitType.includes('words') && self.words.length) targets = self.words;
        if (!targets && splitType.includes('lines') && self.lines.length) targets = self.lines;
        if (!targets) targets = self.chars || self.words || self.lines;
      };

      const splitInstance = new GSAPSplitText(el, {
        type: splitType,
        smartWrap: true,
        autoSplit: splitType === 'lines',
        linesClass: 'split-line',
        wordsClass: 'split-word',
        charsClass: 'split-char',
        reduceWhiteSpace: false,
        onSplit: self => {
          assignTargets(self);
          const tweenConfig = {
            ...to,
            duration,
            ease,
            stagger: delay / 1000,
            onComplete: () => {
              animationCompletedRef.current = true;
              onCompleteRef.current?.();
            },
            willChange: 'transform, opacity',
            force3D: true
          };
          if (!playOnMount) {
            tweenConfig.scrollTrigger = {
              trigger: el,
              start,
              once: true,
              fastScrollEnd: true,
              anticipatePin: 0.4
            };
          }
          const tween = gsap.fromTo(targets, { ...from }, tweenConfig);
          if (playOnMount) {
            /* The parent was rendered hidden (opacity 0, see renderTag);
               the fromTo's immediateRender now has every char at opacity 0,
               so revealing the parent here shows ONLY the un-animated
               letters — the effect plays from there. No plain-text flash. */
            el.style.opacity = '1';
          }
          return tween;
        }
      });

      el._rbsplitInstance = splitInstance;

      return () => {
        ScrollTrigger.getAll().forEach(st => {
          if (st.trigger === el) st.kill();
        });
        try {
          splitInstance.revert();
        } catch (_) {
          /* noop */
        }
        el._rbsplitInstance = null;
      };
    },
    {
      /* playOnMount: exclude fontsLoaded — if the webfont resolves
         mid-animation (a ~0.6s window), a re-run would revert + restart
         the split. The scroll-triggered path keeps fontsLoaded because it
         needs the gate before splitting. */
      dependencies: playOnMount
        ? [
            text,
            delay,
            duration,
            ease,
            splitType,
            JSON.stringify(from),
            JSON.stringify(to),
            playOnMount
          ]
        : [
            text,
            delay,
            duration,
            ease,
            splitType,
            JSON.stringify(from),
            JSON.stringify(to),
            threshold,
            rootMargin,
            fontsLoaded,
            playOnMount
          ],
      scope: ref
    }
  );

  const renderTag = () => {
    const style = {
      textAlign,
      overflow: 'hidden',
      display: 'inline-block',
      whiteSpace: 'normal',
      wordWrap: 'break-word',
      willChange: 'transform, opacity',
      /* playOnMount: start hidden so the plain text can never be seen
         before the split + animation apply. The onSplit handler flips it
         back to 1 at the exact moment the fromTo's immediateRender has
         every char at opacity 0. */
      ...(playOnMount ? { opacity: 0 } : {})
    };
    const classes = `split-parent ${className}`;
    const Tag = tag || 'p';

    return (
      <Tag ref={ref} style={style} className={classes}>
        {text}
      </Tag>
    );
  };
  return renderTag();
};

export default SplitText;
