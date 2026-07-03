import { Routes, Route } from 'react-router-dom';
import NavBar from './components/NavBar';
import EventListPage from './components/EventList/EventListPage';
import EventEditorPage from './components/EventEditor/EventEditorPage';

export default function App() {
  return (
    <>
      <NavBar />
      <main>
        <Routes>
          <Route path="/" element={<EventListPage />} />
          <Route path="/event/:id" element={<EventEditorPage />} />
        </Routes>
      </main>
    </>
  );
}
