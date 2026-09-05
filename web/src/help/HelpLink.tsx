/** Small circled "?" that deep-links into the Help page.
 * Pass `topic` (a help section/subsection id) to open Help with that
 * section expanded, scrolled into view and briefly flashed.
 *
 * Two things here are deliberate:
 *
 * - The click navigates with a FRESH NONCE (see helpTarget.ts) so clicking the
 *   same "?" again re-scrolls and re-flashes instead of doing nothing. The
 *   anchor keeps the plain href so middle-click / copy-link stay shareable,
 *   and so NavBar's capture-phase unsaved-changes guard can still read it.
 * - The handler is a NATIVE listener on the anchor itself, not React's
 *   onClick. On a double-click the first click navigates away, so by the
 *   second click this anchor is detached from the document — React's
 *   delegated root listener never sees it, and the browser was left to follow
 *   the href, FULL-RELOADING the whole app (measured). A listener bound to
 *   the node still fires when the node is detached, so the second click stays
 *   a clean in-app re-navigation. */
import { useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { helpTopicHref, helpTopicNavTo } from './helpTarget';

export default function HelpLink({ topic, title }: { topic?: string; title?: string }) {
  const navigate = useNavigate();
  const ref = useRef<HTMLAnchorElement | null>(null);
  const live = useRef({ topic, navigate, mounted: true });
  live.current.topic = topic;
  live.current.navigate = navigate;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault(); // also stops react-router's own Link handler re-navigating
      // Second click of a double-click: this anchor is already detached and
      // the app has moved on. Swallow it — the first click's jump and flash
      // are the answer; letting the browser follow the href here full-reloads
      // the app (measured).
      if (!live.current.mounted) return;
      live.current.navigate(helpTopicNavTo(live.current.topic));
    };
    el.addEventListener('click', onClick);
    // Deliberately NOT removed on unmount: a listener bound to the node still
    // fires once the node is detached, which is the only way to stop that
    // stray second click. The node (and this closure) are unreachable
    // afterwards, so nothing leaks.
    return () => { live.current.mounted = false; };
  }, []);

  return (
    <Link
      ref={ref}
      to={helpTopicHref(topic)}
      className="help-link"
      title={title ?? 'Help'}
      aria-label={title ?? 'Help'}
      onClick={(e) => e.stopPropagation()}
    >
      ?
    </Link>
  );
}
