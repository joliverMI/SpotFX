/** Small circled "?" that deep-links into the Help page.
 * Pass `topic` (a help section/subsection id) to open Help with that
 * section expanded and scrolled into view. */
import { Link } from 'react-router-dom';

export default function HelpLink({ topic, title }: { topic?: string; title?: string }) {
  const to = topic ? `/help?topic=${encodeURIComponent(topic)}` : '/help';
  return (
    <Link
      to={to}
      className="help-link"
      title={title ?? 'Help'}
      aria-label={title ?? 'Help'}
      onClick={(e) => e.stopPropagation()}
    >
      ?
    </Link>
  );
}
