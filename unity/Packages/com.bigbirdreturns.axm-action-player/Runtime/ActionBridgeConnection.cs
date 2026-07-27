using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public enum ActionBridgeConnectionState
    {
        Disconnected,
        Connecting,
        Connected,
        Faulted,
        Disposed
    }

    public sealed class ActionBridgeConnection : IDisposable
    {
        private readonly int maximumQueuedMessages;
        private readonly int maximumLineBytes;
        private readonly ConcurrentQueue<string> incoming = new ConcurrentQueue<string>();
        private readonly SemaphoreSlim writeGate = new SemaphoreSlim(1, 1);
        private readonly object stateGate = new object();

        private TcpClient client;
        private StreamReader reader;
        private StreamWriter writer;
        private CancellationTokenSource cancellation;
        private Task readTask;
        private int queuedMessages;
        private bool disposed;

        public ActionBridgeConnection(
            int maximumQueuedMessages = ActionBridgeProtocol.DefaultMaximumQueuedMessages,
            int maximumLineBytes = ActionBridgeProtocol.DefaultMaximumLineBytes)
        {
            this.maximumQueuedMessages = Math.Max(8, maximumQueuedMessages);
            this.maximumLineBytes = Math.Max(1024, maximumLineBytes);
        }

        public ActionBridgeConnectionState State { get; private set; } = ActionBridgeConnectionState.Disconnected;
        public string LastError { get; private set; } = string.Empty;
        public bool IsConnected => State == ActionBridgeConnectionState.Connected && client != null && client.Connected;
        public int QueuedMessageCount => Volatile.Read(ref queuedMessages);

        public async Task ConnectAsync(string host, int port)
        {
            ThrowIfDisposed();
            if (string.IsNullOrWhiteSpace(host))
            {
                throw new ArgumentException("Bridge host is empty.", nameof(host));
            }

            lock (stateGate)
            {
                if (State == ActionBridgeConnectionState.Connecting || State == ActionBridgeConnectionState.Connected)
                {
                    throw new InvalidOperationException("The bridge connection is already active.");
                }

                State = ActionBridgeConnectionState.Connecting;
                LastError = string.Empty;
            }

            TcpClient nextClient = new TcpClient
            {
                NoDelay = true,
                ReceiveBufferSize = 256 * 1024,
                SendBufferSize = 256 * 1024
            };

            try
            {
                await nextClient.ConnectAsync(host, port).ConfigureAwait(false);
                NetworkStream stream = nextClient.GetStream();
                UTF8Encoding utf8 = new UTF8Encoding(false, true);

                client = nextClient;
                reader = new StreamReader(stream, utf8, false, 64 * 1024, true);
                writer = new StreamWriter(stream, utf8, 64 * 1024, true)
                {
                    AutoFlush = true,
                    NewLine = "\n"
                };
                cancellation = new CancellationTokenSource();

                lock (stateGate)
                {
                    State = ActionBridgeConnectionState.Connected;
                }

                readTask = ReadLoopAsync(cancellation.Token);
            }
            catch (Exception exception)
            {
                nextClient.Dispose();
                SetFault(exception);
                throw;
            }
        }

        public async Task SendJsonAsync(string json)
        {
            ThrowIfDisposed();
            if (!IsConnected || writer == null)
            {
                throw new InvalidOperationException("The bridge is not connected.");
            }

            if (string.IsNullOrWhiteSpace(json))
            {
                throw new ArgumentException("Bridge JSON is empty.", nameof(json));
            }

            int bytes = Encoding.UTF8.GetByteCount(json);
            if (bytes > maximumLineBytes)
            {
                throw new InvalidOperationException($"Bridge message exceeds the {maximumLineBytes} byte line limit.");
            }

            if (json.IndexOf('\n') >= 0 || json.IndexOf('\r') >= 0)
            {
                throw new InvalidOperationException("Bridge JSONL messages must be serialized onto one physical line.");
            }

            await writeGate.WaitAsync().ConfigureAwait(false);
            try
            {
                await writer.WriteLineAsync(json).ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                SetFault(exception);
                throw;
            }
            finally
            {
                writeGate.Release();
            }
        }

        public bool TryDequeue(out string json)
        {
            if (incoming.TryDequeue(out json))
            {
                Interlocked.Decrement(ref queuedMessages);
                return true;
            }

            json = string.Empty;
            return false;
        }

        public async Task DisconnectAsync()
        {
            if (disposed)
            {
                return;
            }

            CancellationTokenSource tokenSource = cancellation;
            cancellation = null;
            if (tokenSource != null)
            {
                tokenSource.Cancel();
            }

            try
            {
                client?.Close();
                if (readTask != null)
                {
                    await readTask.ConfigureAwait(false);
                }
            }
            catch
            {
                // The socket is intentionally being closed to interrupt ReadLineAsync.
            }
            finally
            {
                tokenSource?.Dispose();
                reader?.Dispose();
                writer?.Dispose();
                client?.Dispose();
                reader = null;
                writer = null;
                client = null;
                readTask = null;
                lock (stateGate)
                {
                    if (State != ActionBridgeConnectionState.Faulted)
                    {
                        State = ActionBridgeConnectionState.Disconnected;
                    }
                }
            }
        }

        private async Task ReadLoopAsync(CancellationToken token)
        {
            try
            {
                while (!token.IsCancellationRequested && reader != null)
                {
                    string line = await reader.ReadLineAsync().ConfigureAwait(false);
                    if (line == null)
                    {
                        throw new EndOfStreamException("The action bridge closed the connection.");
                    }

                    int bytes = Encoding.UTF8.GetByteCount(line);
                    if (bytes > maximumLineBytes)
                    {
                        throw new InvalidDataException($"Bridge response exceeds the {maximumLineBytes} byte line limit.");
                    }

                    int nextCount = Interlocked.Increment(ref queuedMessages);
                    if (nextCount > maximumQueuedMessages)
                    {
                        Interlocked.Decrement(ref queuedMessages);
                        throw new InvalidDataException($"Bridge response queue exceeded {maximumQueuedMessages} messages.");
                    }

                    incoming.Enqueue(line);
                }
            }
            catch (Exception exception)
            {
                if (!token.IsCancellationRequested && !disposed)
                {
                    SetFault(exception);
                }
            }
        }

        private void SetFault(Exception exception)
        {
            lock (stateGate)
            {
                LastError = exception == null ? "Unknown bridge fault." : exception.Message;
                State = ActionBridgeConnectionState.Faulted;
            }
        }

        private void ThrowIfDisposed()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(ActionBridgeConnection));
            }
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            try
            {
                cancellation?.Cancel();
                client?.Close();
            }
            finally
            {
                cancellation?.Dispose();
                reader?.Dispose();
                writer?.Dispose();
                client?.Dispose();
                writeGate.Dispose();
                lock (stateGate)
                {
                    State = ActionBridgeConnectionState.Disposed;
                }
            }
        }
    }
}
