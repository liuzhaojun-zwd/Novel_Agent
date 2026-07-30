import { useState } from "react";
import { api } from "../api";

export default function AuthPanel({ initialized, onAuthenticated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const result = initialized
        ? await api.login(username, password)
        : await api.bootstrap(username, password);
      onAuthenticated(result.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return <main className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
    <form onSubmit={submit} className="w-full max-w-sm bg-white dark:bg-gray-800 border dark:border-gray-700 rounded-xl shadow-sm p-6 space-y-4">
      <div><h1 className="text-xl font-bold dark:text-white">Novel_Agent</h1>
        <p className="text-sm text-gray-500 mt-1">{initialized ? "登录创作工作台" : "创建首位管理员并接管现有项目"}</p></div>
      <label className="block text-sm dark:text-gray-300">用户名
        <input value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} required autoComplete="username"
          className="mt-1 w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" /></label>
      <label className="block text-sm dark:text-gray-300">密码（至少 10 位）
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={10} required
          autoComplete={initialized ? "current-password" : "new-password"}
          className="mt-1 w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600" /></label>
      {error && <div className="text-sm text-red-600">{error}</div>}
      <button disabled={busy} className="w-full py-2.5 rounded-lg bg-indigo-600 text-white disabled:opacity-50">
        {busy ? "处理中..." : initialized ? "登录" : "初始化系统"}
      </button>
    </form>
  </main>;
}
