using System.Collections.Concurrent;
using System.Runtime.InteropServices;

namespace HamCheckin.Native.App.Media;

internal static class WinMm
{
    internal const uint CallbackFunction = 0x00030000;
    internal const uint WimData = 0x03C0;
    internal const uint WaveMapper = 0xFFFFFFFF;

    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    internal delegate void WaveInProc(
        nint waveInHandle,
        uint message,
        nint instance,
        nint parameter1,
        nint parameter2);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    internal struct WaveInCaps
    {
        internal ushort ManufacturerId;
        internal ushort ProductId;
        internal uint DriverVersion;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        internal string ProductName;

        internal uint Formats;
        internal ushort Channels;
        internal ushort Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct WaveFormatEx
    {
        internal ushort FormatTag;
        internal ushort Channels;
        internal uint SamplesPerSecond;
        internal uint AverageBytesPerSecond;
        internal ushort BlockAlign;
        internal ushort BitsPerSample;
        internal ushort ExtraSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct WaveHeader
    {
        internal nint Data;
        internal int BufferLength;
        internal int BytesRecorded;
        internal nint User;
        internal uint Flags;
        internal uint Loops;
        internal nint Next;
        internal nint Reserved;
    }

    [DllImport("winmm.dll")]
    internal static extern uint waveInGetNumDevs();

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    internal static extern uint waveInGetDevCaps(
        uint deviceId,
        out WaveInCaps capabilities,
        uint capabilitiesSize);

    [DllImport("winmm.dll")]
    internal static extern uint waveInOpen(
        out nint waveInHandle,
        uint deviceId,
        ref WaveFormatEx format,
        WaveInProc callback,
        nint instance,
        uint flags);

    [DllImport("winmm.dll")]
    internal static extern uint waveInPrepareHeader(
        nint waveInHandle,
        nint header,
        uint headerSize);

    [DllImport("winmm.dll")]
    internal static extern uint waveInUnprepareHeader(
        nint waveInHandle,
        nint header,
        uint headerSize);

    [DllImport("winmm.dll")]
    internal static extern uint waveInAddBuffer(
        nint waveInHandle,
        nint header,
        uint headerSize);

    [DllImport("winmm.dll")]
    internal static extern uint waveInStart(nint waveInHandle);

    [DllImport("winmm.dll")]
    internal static extern uint waveInStop(nint waveInHandle);

    [DllImport("winmm.dll")]
    internal static extern uint waveInReset(nint waveInHandle);

    [DllImport("winmm.dll")]
    internal static extern uint waveInClose(nint waveInHandle);
}

public sealed class MicrophoneCapture : IDisposable
{
    private const int BufferCount = 4;
    private const int BufferSize = 16 * 1024;
    private readonly object _gate = new();
    private readonly int _deviceId;
    private readonly int _sampleRate;
    private readonly WinMm.WaveInProc _callback;
    private readonly ConcurrentDictionary<nint, AudioBuffer> _buffers = new();
    private nint _waveInHandle;
    private bool _stopping;

    public MicrophoneCapture(int deviceId, int sampleRate = 44100)
    {
        _deviceId = deviceId;
        _sampleRate = sampleRate;
        _callback = OnWaveInCallback;
    }

    public event EventHandler<MicrophoneLevelEventArgs>? LevelChanged;
    // Audio buffers are short-lived callback data.  Keep this as an Action rather
    // than an EventHandler because ReadOnlyMemory<byte> is not an EventArgs type.
    public event Action<ReadOnlyMemory<byte>>? AudioData;

    public bool IsRunning
    {
        get
        {
            lock (_gate)
            {
                return _waveInHandle != 0 && !_stopping;
            }
        }
    }

    public static IReadOnlyList<MicrophoneDevice> EnumerateDevices()
    {
        var count = WinMm.waveInGetNumDevs();
        var result = new List<MicrophoneDevice>((int)count);
        for (var index = 0; index < count; index++)
        {
            if (WinMm.waveInGetDevCaps(
                    (uint)index,
                    out var caps,
                    (uint)Marshal.SizeOf<WinMm.WaveInCaps>()) != 0)
            {
                continue;
            }

            var name = caps.ProductName?.Trim('\0', ' ', '\t');
            result.Add(new MicrophoneDevice(
                (int)index,
                string.IsNullOrWhiteSpace(name) ? $"麦克风设备 {index + 1}" : name));
        }

        return result;
    }

    public void Start()
    {
        nint handle = 0;
        Exception? failure = null;
        lock (_gate)
        {
            if (_waveInHandle != 0)
            {
                return;
            }

            var format = new WinMm.WaveFormatEx
            {
                FormatTag = 1,
                Channels = 1,
                SamplesPerSecond = (uint)_sampleRate,
                BitsPerSample = 16,
                BlockAlign = 2,
                AverageBytesPerSecond = (uint)(_sampleRate * 2),
                ExtraSize = 0
            };

            var device = _deviceId < 0 ? WinMm.WaveMapper : (uint)_deviceId;
            try
            {
                var result = WinMm.waveInOpen(
                    out handle,
                    device,
                    ref format,
                    _callback,
                    0,
                    WinMm.CallbackFunction);
                if (result != 0)
                {
                    throw new InvalidOperationException(
                        $"无法打开麦克风，Windows waveIn 错误码：{result}。请检查 Windows 麦克风权限和设备占用情况。");
                }

                _waveInHandle = handle;
                _stopping = false;
                for (var index = 0; index < BufferCount; index++)
                {
                    var audioBuffer = new AudioBuffer(BufferSize);
                    var headerSize = (uint)Marshal.SizeOf<WinMm.WaveHeader>();
                    var prepareResult = WinMm.waveInPrepareHeader(handle, audioBuffer.Header, headerSize);
                    if (prepareResult != 0)
                    {
                        throw new InvalidOperationException($"无法准备麦克风缓冲区，错误码：{prepareResult}。");
                    }

                    audioBuffer.IsPrepared = true;
                    _buffers[audioBuffer.Header] = audioBuffer;
                    var addResult = WinMm.waveInAddBuffer(handle, audioBuffer.Header, headerSize);
                    if (addResult != 0)
                    {
                        throw new InvalidOperationException($"无法加入麦克风缓冲区，错误码：{addResult}。");
                    }
                }

                var startResult = WinMm.waveInStart(handle);
                if (startResult != 0)
                {
                    throw new InvalidOperationException($"无法开始麦克风采集，错误码：{startResult}。");
                }
            }
            catch (Exception exception)
            {
                failure = exception;
                if (handle != 0)
                {
                    _stopping = true;
                }
            }
        }

        // Do not stop WinMM while holding _gate.  A waveIn callback can be
        // waiting for that lock while waveInReset waits for the callback.
        if (handle != 0 && failure is not null)
        {
            StopCore(handle);
        }

        if (failure is not null)
        {
            throw failure;
        }
    }

    public void Stop()
    {
        nint handle;
        lock (_gate)
        {
            if (_waveInHandle == 0)
            {
                return;
            }

            _stopping = true;
            handle = _waveInHandle;
        }

        StopCore(handle);
    }

    public void Dispose() => Stop();

    private void OnWaveInCallback(
        nint waveInHandle,
        uint message,
        nint instance,
        nint parameter1,
        nint parameter2)
    {
        if (message != WinMm.WimData || parameter1 == 0)
        {
            return;
        }

        byte[]? data = null;
        float level = 0;
        lock (_gate)
        {
            if (_stopping || _waveInHandle != waveInHandle || !_buffers.TryGetValue(parameter1, out var buffer))
            {
                return;
            }

            var header = Marshal.PtrToStructure<WinMm.WaveHeader>(buffer.Header);
            var bytesRecorded = Math.Clamp(header.BytesRecorded, 0, buffer.Length);
            if (bytesRecorded > 0)
            {
                data = new byte[bytesRecorded];
                Marshal.Copy(buffer.Data, data, 0, bytesRecorded);
                level = CalculatePeak(data);
            }

            if (!_stopping && _waveInHandle == waveInHandle)
            {
                _ = WinMm.waveInAddBuffer(waveInHandle, buffer.Header,
                    (uint)Marshal.SizeOf<WinMm.WaveHeader>());
            }
        }

        if (data is not null)
        {
            LevelChanged?.Invoke(this, new MicrophoneLevelEventArgs(level));
            AudioData?.Invoke(data);
        }
    }

    private void StopCore(nint handle)
    {
        lock (_gate)
        {
            if (_waveInHandle != handle)
            {
                return;
            }

            _stopping = true;
        }

        _ = WinMm.waveInStop(handle);
        _ = WinMm.waveInReset(handle);
        var headerSize = (uint)Marshal.SizeOf<WinMm.WaveHeader>();
        AudioBuffer[] buffers;
        lock (_gate)
        {
            buffers = _buffers.Values.ToArray();
            _buffers.Clear();
            if (_waveInHandle == handle)
            {
                _waveInHandle = 0;
                _stopping = false;
            }
        }

        foreach (var buffer in buffers)
        {
            if (buffer.IsPrepared)
            {
                _ = WinMm.waveInUnprepareHeader(handle, buffer.Header, headerSize);
            }

            buffer.Dispose();
        }

        _ = WinMm.waveInClose(handle);
        lock (_gate)
        {
            if (_waveInHandle == handle)
            {
                _waveInHandle = 0;
                _stopping = false;
            }
        }
    }

    private static float CalculatePeak(byte[] data)
    {
        var peak = 0;
        for (var index = 0; index + 1 < data.Length; index += 2)
        {
            var sample = Math.Abs(BitConverter.ToInt16(data, index));
            if (sample > peak)
            {
                peak = sample;
            }
        }

        return peak / 32768f;
    }

    private sealed class AudioBuffer : IDisposable
    {
        internal AudioBuffer(int length)
        {
            Length = length;
            Data = Marshal.AllocHGlobal(length);
            Header = Marshal.AllocHGlobal(Marshal.SizeOf<WinMm.WaveHeader>());
            Marshal.StructureToPtr(new WinMm.WaveHeader
            {
                Data = Data,
                BufferLength = length
            }, Header, false);
        }

        internal nint Data { get; }
        internal nint Header { get; }
        internal int Length { get; }
        internal bool IsPrepared { get; set; }

        public void Dispose()
        {
            if (Data != 0)
            {
                Marshal.FreeHGlobal(Data);
            }

            if (Header != 0)
            {
                Marshal.FreeHGlobal(Header);
            }
        }
    }
}
