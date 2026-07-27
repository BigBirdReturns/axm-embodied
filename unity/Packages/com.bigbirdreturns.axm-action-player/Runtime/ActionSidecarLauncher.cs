using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Threading.Tasks;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public sealed class ActionSidecarLauncher : MonoBehaviour
    {
        [SerializeField] private bool launchOnStart = true;
        [SerializeField] private string arcRepositoryPath = string.Empty;
        [SerializeField] private string executable = "npx";
        [SerializeField] private string arguments = "vite-node src/action-bridge/cli.ts --host 127.0.0.1 --port 47631";
        [SerializeField] private string healthHost = "127.0.0.1";
        [SerializeField] private int healthPort = ActionBridgeProtocol.DefaultPort;
        [SerializeField, Min(0.5f)] private float startupTimeoutSeconds = 20f;
        [SerializeField] private bool stopWithUnity = true;

        private Process process;
        private string logDirectory = string.Empty;

        public event Action Ready;
        public event Action<string> Failed;

        public bool IsRunning => process != null && !process.HasExited;
        public string LogDirectory => logDirectory;

        private async void Start()
        {
            if (launchOnStart)
            {
                await LaunchAsync();
            }
        }

        private void OnDestroy()
        {
            if (stopWithUnity)
            {
                StopSidecar();
            }
        }

        public async Task LaunchAsync()
        {
#if UNITY_ANDROID || UNITY_IOS || UNITY_WEBGL
            Failed?.Invoke("Local process launch is unavailable on this Unity platform. Configure the bridge driver to use a LAN authority host.");
            await Task.CompletedTask;
#else
            if (IsRunning)
            {
                return;
            }

            if (string.IsNullOrWhiteSpace(arcRepositoryPath) || !Directory.Exists(arcRepositoryPath))
            {
                Failed?.Invoke("Arc repository path is absent: " + arcRepositoryPath);
                return;
            }

            logDirectory = Path.Combine(Application.persistentDataPath, "axm", "action-sidecar");
            Directory.CreateDirectory(logDirectory);
            string stdoutPath = Path.Combine(logDirectory, "stdout.log");
            string stderrPath = Path.Combine(logDirectory, "stderr.log");

            string command = executable;
#if UNITY_STANDALONE_WIN || UNITY_EDITOR_WIN
            if (string.Equals(command, "npx", StringComparison.OrdinalIgnoreCase))
            {
                command = "npx.cmd";
            }
#endif

            try
            {
                ProcessStartInfo startInfo = new ProcessStartInfo
                {
                    FileName = command,
                    Arguments = arguments,
                    WorkingDirectory = arcRepositoryPath,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
                process.OutputDataReceived += (_, eventArgs) => AppendLine(stdoutPath, eventArgs.Data);
                process.ErrorDataReceived += (_, eventArgs) => AppendLine(stderrPath, eventArgs.Data);
                process.Exited += (_, __) =>
                {
                    if (process != null && process.ExitCode != 0)
                    {
                        Failed?.Invoke("Arc action sidecar exited with code " + process.ExitCode + ". Logs: " + logDirectory);
                    }
                };

                if (!process.Start())
                {
                    Failed?.Invoke("Arc action sidecar process did not start.");
                    return;
                }
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();

                float deadline = Time.realtimeSinceStartup + Mathf.Max(0.5f, startupTimeoutSeconds);
                while (Time.realtimeSinceStartup < deadline)
                {
                    if (process.HasExited)
                    {
                        Failed?.Invoke("Arc action sidecar exited during startup. Logs: " + logDirectory);
                        return;
                    }

                    if (await PortAcceptsConnectionAsync(healthHost, healthPort))
                    {
                        Ready?.Invoke();
                        return;
                    }

                    await Task.Delay(100);
                }

                Failed?.Invoke("Arc action sidecar did not open its bridge port before timeout. Logs: " + logDirectory);
            }
            catch (Exception exception)
            {
                Failed?.Invoke(exception.Message);
            }
#endif
        }

        public void StopSidecar()
        {
#if !UNITY_ANDROID && !UNITY_IOS && !UNITY_WEBGL
            if (process == null)
            {
                return;
            }

            try
            {
                if (!process.HasExited)
                {
                    process.Kill();
                    process.WaitForExit(3000);
                }
            }
            catch
            {
                // Unity teardown should continue even when the child process already ended.
            }
            finally
            {
                process.Dispose();
                process = null;
            }
#endif
        }

        private static async Task<bool> PortAcceptsConnectionAsync(string host, int port)
        {
            try
            {
                using (TcpClient probe = new TcpClient())
                {
                    Task connect = probe.ConnectAsync(host, Mathf.Clamp(port, 1, 65535));
                    Task completed = await Task.WhenAny(connect, Task.Delay(250));
                    return completed == connect && probe.Connected;
                }
            }
            catch
            {
                return false;
            }
        }

        private static void AppendLine(string path, string line)
        {
            if (line == null)
            {
                return;
            }

            lock (typeof(ActionSidecarLauncher))
            {
                File.AppendAllText(path, line + Environment.NewLine);
            }
        }
    }
}
