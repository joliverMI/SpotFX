import { useEffect, useState } from 'react';

/** Phone-portrait breakpoint — the owner drives SPECTRA from his phone in
 * the room, so narrow layouts are a first-class arrangement, not a
 * squeezed desktop (ScenesPage swaps its two panes for a drawer picker). */
const QUERY = '(max-width: 720px)';

export default function useIsPhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia(QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const onChange = () => setPhone(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return phone;
}
