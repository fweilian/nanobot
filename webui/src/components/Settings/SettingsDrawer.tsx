import { X } from 'lucide-react';
import { useConfigStore } from '../../stores/configStore';

interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const { apiUrl, apiKey, theme, setApiUrl, setApiKey, setTheme } = useConfigStore();

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50" onClick={onClose} />
      <div className="w-80 h-full bg-white dark:bg-gray-900 shadow-xl p-6 overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold">设置</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X size={20} />
          </button>
        </div>

        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium mb-2">API 地址</label>
            <input
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="http://localhost:8890"
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">API Key (Bearer Token)</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="输入 API Key"
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-800"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">主题</label>
            <div className="flex gap-2">
              <button
                onClick={() => setTheme('light')}
                className={`flex-1 px-3 py-2 rounded-lg border text-sm ${
                  theme === 'light'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-600'
                    : 'border-gray-300'
                }`}
              >
                浅色
              </button>
              <button
                onClick={() => setTheme('dark')}
                className={`flex-1 px-3 py-2 rounded-lg border text-sm ${
                  theme === 'dark'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-600'
                    : 'border-gray-300'
                }`}
              >
                深色
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
