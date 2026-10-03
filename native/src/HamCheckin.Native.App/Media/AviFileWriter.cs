using System.IO;
using System.Text;

namespace HamCheckin.Native.App.Media;

internal sealed class AviFileWriter : IDisposable
{
    private readonly object _gate = new();
    private readonly FileStream _stream;
    private readonly BinaryWriter _writer;
    private readonly int _width;
    private readonly int _height;
    private readonly int _framesPerSecond;
    private readonly int _sampleRate;
    private readonly int _channels;
    private readonly long _riffSizePosition;
    private readonly long _moviSizePosition;
    private readonly long _moviDataStart;
    private readonly long _avihDataPosition;
    private readonly long _videoStrhDataPosition;
    private readonly long _audioStrhDataPosition;
    private readonly List<IndexEntry> _index = new();
    private long _videoFrames;
    private long _audioBytes;
    private int _maxVideoFrameBytes;
    private bool _completed;

    public AviFileWriter(
        string outputPath,
        int width,
        int height,
        int framesPerSecond,
        int sampleRate,
        int channels = 1)
    {
        if (width <= 0 || height <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), "录制尺寸无效。");
        }

        _width = width;
        _height = height;
        _framesPerSecond = Math.Clamp(framesPerSecond, 1, 30);
        _sampleRate = sampleRate;
        _channels = channels;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        _stream = new FileStream(outputPath, FileMode.Create, FileAccess.ReadWrite, FileShare.Read,
            1024 * 1024, FileOptions.SequentialScan);
        _writer = new BinaryWriter(_stream, Encoding.ASCII, leaveOpen: true);

        WriteFourCc("RIFF");
        _riffSizePosition = _stream.Position;
        WriteInt32(0);
        WriteFourCc("AVI ");

        var hdrl = BeginList("hdrl", out var hdrlSizePosition);
        _avihDataPosition = WriteAvih();
        _videoStrhDataPosition = WriteVideoStreamHeader();
        _audioStrhDataPosition = WriteAudioStreamHeader();
        var hdrlEnd = _stream.Position;
        PatchInt32(hdrlSizePosition, checked((int)(hdrlEnd - (hdrlSizePosition + 4))));
        _ = hdrl;

        BeginList("movi", out _moviSizePosition);
        _moviDataStart = _stream.Position;
    }

    public long VideoFrames => Interlocked.Read(ref _videoFrames);
    public long AudioBytes => Interlocked.Read(ref _audioBytes);

    public void WriteVideoFrame(byte[] jpeg)
    {
        ArgumentNullException.ThrowIfNull(jpeg);
        lock (_gate)
        {
            EnsureOpen();
            WriteChunk("00dc", jpeg, 0x10);
            _videoFrames++;
            _maxVideoFrameBytes = Math.Max(_maxVideoFrameBytes, jpeg.Length);
        }
    }

    public void WriteAudio(byte[] pcm)
    {
        ArgumentNullException.ThrowIfNull(pcm);
        if (pcm.Length == 0)
        {
            return;
        }

        lock (_gate)
        {
            EnsureOpen();
            WriteChunk("01wb", pcm, 0);
            _audioBytes += pcm.Length;
        }
    }

    public void Complete()
    {
        lock (_gate)
        {
            if (_completed)
            {
                return;
            }

            var moviEnd = _stream.Position;
            WriteFourCc("idx1");
            WriteInt32(checked(_index.Count * 16));
            foreach (var entry in _index)
            {
                WriteFourCc(entry.Id);
                WriteInt32(entry.Flags);
                WriteInt32(entry.Offset);
                WriteInt32(entry.Size);
            }

            PatchHeaders();
            PatchInt32(_moviSizePosition, checked((int)(moviEnd - (_moviSizePosition + 4))));
            PatchInt32(_riffSizePosition, checked((int)(_stream.Length - 8)));
            _writer.Flush();
            _stream.Flush(true);
            _completed = true;
        }
    }

    public void Dispose()
    {
        try
        {
            Complete();
        }
        finally
        {
            _writer.Dispose();
            _stream.Dispose();
        }
    }

    private long BeginList(string type, out long sizePosition)
    {
        WriteFourCc("LIST");
        sizePosition = _stream.Position;
        WriteInt32(0);
        WriteFourCc(type);
        return sizePosition;
    }

    private long WriteAvih()
    {
        WriteFourCc("avih");
        WriteInt32(56);
        var dataPosition = _stream.Position;
        for (var index = 0; index < 14; index++)
        {
            WriteInt32(0);
        }

        return dataPosition;
    }

    private long WriteVideoStreamHeader()
    {
        WriteFourCc("LIST");
        var sizePosition = _stream.Position;
        WriteInt32(0);
        WriteFourCc("strl");
        WriteFourCc("strh");
        WriteInt32(56);
        var dataPosition = _stream.Position;
        WriteFourCc("vids");
        WriteFourCc("MJPG");
        WriteInt32(0);
        WriteUInt16(0);
        WriteUInt16(0);
        WriteInt32(0);
        WriteInt32(1);
        WriteInt32(_framesPerSecond);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(7500);
        WriteInt32(0);
        WriteInt16(0);
        WriteInt16(0);
        WriteInt16((short)Math.Min(_width, short.MaxValue));
        WriteInt16((short)Math.Min(_height, short.MaxValue));
        var afterHeader = _stream.Position;
        WriteVideoStreamFormat();
        PatchInt32(sizePosition, checked((int)(afterHeader - (sizePosition + 4)) +
            checked((int)(_stream.Position - afterHeader))));
        return dataPosition;
    }

    private void WriteVideoStreamFormat()
    {
        WriteFourCc("strf");
        WriteInt32(40);
        WriteInt32(40);
        WriteInt32(_width);
        WriteInt32(_height);
        WriteUInt16(1);
        WriteUInt16(24);
        WriteFourCc("MJPG");
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(0);
    }

    private long WriteAudioStreamHeader()
    {
        WriteFourCc("LIST");
        var sizePosition = _stream.Position;
        WriteInt32(0);
        WriteFourCc("strl");
        WriteFourCc("strh");
        WriteInt32(56);
        var dataPosition = _stream.Position;
        WriteFourCc("auds");
        WriteInt32(0);
        WriteInt32(0);
        WriteUInt16(0);
        WriteUInt16(0);
        WriteInt32(0);
        WriteInt32(_channels * 2);
        WriteInt32(_sampleRate * _channels * 2);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(0);
        WriteInt32(-1);
        WriteInt32(_channels * 2);
        WriteInt16(0);
        WriteInt16(0);
        WriteInt16(0);
        WriteInt16(0);
        var afterHeader = _stream.Position;
        WriteAudioStreamFormat();
        PatchInt32(sizePosition, checked((int)(afterHeader - (sizePosition + 4)) +
            checked((int)(_stream.Position - afterHeader))));
        return dataPosition;
    }

    private void WriteAudioStreamFormat()
    {
        WriteFourCc("strf");
        WriteInt32(16);
        WriteUInt16(1);
        WriteUInt16((ushort)_channels);
        WriteInt32(_sampleRate);
        WriteInt32(_sampleRate * _channels * 2);
        WriteUInt16((ushort)(_channels * 2));
        WriteUInt16(16);
    }

    private void WriteChunk(string id, byte[] data, int flags)
    {
        var offset = checked((int)(_stream.Position - _moviDataStart));
        WriteFourCc(id);
        WriteInt32(data.Length);
        _stream.Write(data, 0, data.Length);
        if ((data.Length & 1) != 0)
        {
            _writer.Write((byte)0);
        }

        _index.Add(new IndexEntry(id, flags, offset, data.Length));
    }

    private void PatchHeaders()
    {
        var maxBytes = Math.Max(
            _maxVideoFrameBytes * _framesPerSecond,
            _sampleRate * _channels * 2);
        PatchInt32(_avihDataPosition, 1_000_000 / _framesPerSecond);
        PatchInt32(_avihDataPosition + 4, maxBytes);
        PatchInt32(_avihDataPosition + 12, 0x10);
        PatchInt32(_avihDataPosition + 16, checked((int)_videoFrames));
        PatchInt32(_avihDataPosition + 24, 2);
        PatchInt32(_avihDataPosition + 28, Math.Max(_maxVideoFrameBytes, 16 * 1024));
        PatchInt32(_avihDataPosition + 32, _width);
        PatchInt32(_avihDataPosition + 36, _height);
        PatchInt32(_videoStrhDataPosition + 32, checked((int)_videoFrames));
        PatchInt32(_videoStrhDataPosition + 36, _maxVideoFrameBytes);
        PatchInt32(_audioStrhDataPosition + 32, checked((int)(_audioBytes / (_channels * 2))));
        PatchInt32(_audioStrhDataPosition + 36, _sampleRate * _channels * 2);
    }

    private void PatchInt32(long position, int value)
    {
        var current = _stream.Position;
        _stream.Position = position;
        _writer.Write(value);
        _stream.Position = current;
    }

    private void WriteFourCc(string value)
    {
        if (value.Length != 4)
        {
            throw new ArgumentException("AVI FourCC 必须是 4 个字符。", nameof(value));
        }

        _writer.Write(Encoding.ASCII.GetBytes(value));
    }

    private void WriteInt32(int value) => _writer.Write(value);
    private void WriteUInt16(ushort value) => _writer.Write(value);
    private void WriteInt16(short value) => _writer.Write(value);

    private void EnsureOpen()
    {
        ObjectDisposedException.ThrowIf(_completed, this);
    }

    private sealed record IndexEntry(string Id, int Flags, int Offset, int Size);
}
