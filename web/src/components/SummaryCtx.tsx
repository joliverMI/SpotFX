import { createContext, useContext } from 'react';
import type { SummaryContext } from '../types/summaries';

/** Lookup maps (events by id, color-set names) shared by every card for summaries. */
const Ctx = createContext<SummaryContext>({});

export const SummaryProvider = Ctx.Provider;
export const useSummaryCtx = () => useContext(Ctx);
