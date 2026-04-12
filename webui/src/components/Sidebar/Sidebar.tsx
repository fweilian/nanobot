import { Settings } from 'lucide-react';
import { AgentSelector } from './AgentSelector';
import { SessionList } from './SessionList';

interface SidebarProps {
  onSettingsClick: () => void;
}

export function Sidebar({ onSettingsClick }: SidebarProps) {
  return (
    <div className="w-64 h-full flex flex-col bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <h1 className="font-bold text-lg">Nanobot</h1>
        <button
          onClick={onSettingsClick}
          className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800"
        >
          <Settings size={18} />
        </button>
      </div>
      <AgentSelector />
      <SessionList />
    </div>
  );
}
