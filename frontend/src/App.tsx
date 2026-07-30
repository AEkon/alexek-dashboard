import React, { useState } from 'react';
import Jobs from './Jobs';
import Forum from './Forum';

type View = 'jobs' | 'forum';

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>('jobs');

  return (
    <div className="app">
      <header className="app-header">
        <h1>Dashboard</h1>
        <nav className="main-nav">
          <button
            className={`nav-button ${currentView === 'jobs' ? 'active' : ''}`}
            onClick={() => setCurrentView('jobs')}
          >
            💼 Jobs
          </button>
          <button
            className={`nav-button ${currentView === 'forum' ? 'active' : ''}`}
            onClick={() => setCurrentView('forum')}
          >
            💬 Forum
          </button>
        </nav>
      </header>
      <main className="app-main">
        <section className="dashboard-section">
          {currentView === 'jobs' ? <Jobs /> : <Forum />}
        </section>
      </main>
    </div>
  );
};

export default App;
