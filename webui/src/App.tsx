import { useEffect } from 'react';
import { MainLayout } from './components/Layout/MainLayout';
import { useConfigStore } from './stores/configStore';

function App() {
  const { theme } = useConfigStore();

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  return <MainLayout />;
}

export default App;
