import { useState } from 'react';
import { Sidebar } from '../Sidebar/Sidebar';
import { MessageList } from '../Chat/MessageList';
import { ChatInput } from '../Chat/ChatInput';
import { SettingsDrawer } from '../Settings/SettingsDrawer';
import { useAgentStore } from '../../stores/agentStore';

export function MainLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { selectedAgent } = useAgentStore();

  return (
    <div className="flex h-screen">
      <Sidebar onSettingsClick={() => setSettingsOpen(true)} />
      <div className="flex-1 flex flex-col">
        <div className="h-14 px-4 flex items-center border-b border-gray-200 dark:border-gray-700">
          {selectedAgent ? (
            <span className="font-medium">{selectedAgent.name}</span>
          ) : (
            <span className="text-gray-500">未选择 Agent</span>
          )}
        </div>
        <MessageList />
        <ChatInput />
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
