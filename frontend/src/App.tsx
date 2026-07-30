import React from 'react';
import Jobs from './Jobs';
import Forum from './Forum';

const App: React.FC = () => {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Dashboard</h1>
      </header>
      <main className="app-main">
        <section className="dashboard-section">
          <Jobs />
        </section>
        <section className="dashboard-section">
          <Forum />
        </section>
      </main>
    </div>
  );
};

export default App;
