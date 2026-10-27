import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import GuestApp from './GuestApp';
import './guest.css';

createRoot(document.getElementById('root')!).render(<StrictMode><GuestApp /></StrictMode>);
