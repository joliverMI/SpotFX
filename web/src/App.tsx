import { Routes, Route } from 'react-router-dom';
import NavBar from './components/NavBar';
import { ToastProvider } from './components/Toast';
import BuilderPage from './builder/BuilderPage';
import EventListPage from './components/EventList/EventListPage';
import EventEditorPage from './components/EventEditor/EventEditorPage';

export default function App() {
  return (
    <>
      <ToastProvider>
      <NavBar />
      <main>
        <Routes>
          <Route path="/" element={<EventListPage />} />
          <Route path="/event/:id" element={<EventEditorPage />} />
          <Route path="/builder" element={<BuilderPage />} />
        </Routes>
      </main>
      </ToastProvider>
    </>
  );
}
