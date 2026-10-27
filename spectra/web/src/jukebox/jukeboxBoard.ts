/** The board's words on the master's pages (SpotFX services/jukebox/board.py;
 * the plan's §1 rule 11, §2.2, D1 (a)): who added a song, its ▲, and whether
 * guests see a people board. Pure, so scripts/check_jukebox_editor.mjs can
 * drive it. No game words: the board ranks songs, and a people board is his
 * switch (they ship off). */
import type { BoardBy, BoardSong, BoardSettings, PeopleBoard } from './types';

export function byWords(by: BoardBy): string {
  return by.kind === 'set' ? "the host's set" : by.kind === 'host' ? 'added by the host'
    : `added by ${by.name}`;
}

/** "added by Disco Ana · ▲ 3 · played 2 times" */
export function boardSongLine(s: BoardSong): string {
  return [byWords(s.by), `▲ ${s.ups}`, s.plays > 1 ? `played ${s.plays} times` : '']
    .filter(Boolean).join(' · ');
}

/** A people board's heading on the host's own card: what it counts, and
 *  whether guests see it (they ship off — the plan's §2.2 flag). */
export function peopleHeading(p: PeopleBoard): string {
  return `${p.title} — ${p.unit}${p.shown ? '' : ' (guests don\'t see this)'}`;
}

/** The TV page shows a people board only when guests see it too. */
export function tvPeople(people: PeopleBoard[]): PeopleBoard[] {
  return people.filter((p) => p.shown);
}

/** The TV page's own switch, in words, when it is off. */
export function tvOffLine(s: BoardSettings | undefined): string {
  return s && !s.board_on_tv
    ? "The board is off for the TV. Turn on \"On the TV\" in the Jukebox page's Guests tab (the Board card)."
    : '';
}
