using System.Buffers.Binary;
using System.Text;

namespace HamCheckin.Native.Core.Catalogs;

/// <summary>
/// 工信部公开查询接口使用的 SM3 摘要。保持在原生核心内，避免把 Python/Qt
/// 运行时带进 Windows 版；该实现只用于请求签名，不参与现场录入热路径。
/// </summary>
internal static class Sm3
{
    public static string HashHex(string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        var digest = Hash(bytes);
        return Convert.ToHexString(digest).ToLowerInvariant();
    }

    private static byte[] Hash(ReadOnlySpan<byte> input)
    {
        var paddedLength = ((input.Length + 9 + 63) / 64) * 64;
        var padded = new byte[paddedLength];
        input.CopyTo(padded);
        padded[input.Length] = 0x80;
        BinaryPrimitives.WriteUInt64BigEndian(padded.AsSpan(padded.Length - 8), (ulong)input.Length * 8);

        var state = new uint[]
        {
            0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
            0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E
        };
        var w = new uint[68];
        var w1 = new uint[64];

        for (var offset = 0; offset < padded.Length; offset += 64)
        {
            for (var index = 0; index < 16; index++)
            {
                w[index] = BinaryPrimitives.ReadUInt32BigEndian(padded.AsSpan(offset + index * 4, 4));
            }
            for (var index = 16; index < 68; index++)
            {
                w[index] = P1(w[index - 16] ^ w[index - 9] ^ RotateLeft(w[index - 3], 15))
                    ^ RotateLeft(w[index - 13], 7) ^ w[index - 6];
            }
            for (var index = 0; index < 64; index++)
            {
                w1[index] = w[index] ^ w[index + 4];
            }

            var a = state[0]; var b = state[1]; var c = state[2]; var d = state[3];
            var e = state[4]; var f = state[5]; var g = state[6]; var h = state[7];
            for (var j = 0; j < 64; j++)
            {
                var t = j <= 15 ? 0x79CC4519u : 0x7A879D8Au;
                var ss1 = RotateLeft(unchecked(RotateLeft(a, 12) + e + RotateLeft(t, j)), 7);
                var ss2 = ss1 ^ RotateLeft(a, 12);
                var tt1 = unchecked(Ff(a, b, c, j) + d + ss2 + w1[j]);
                var tt2 = unchecked(Gg(e, f, g, j) + h + ss1 + w[j]);
                d = c;
                c = RotateLeft(b, 9);
                b = a;
                a = tt1;
                h = g;
                g = RotateLeft(f, 19);
                f = e;
                e = P0(tt2);
            }

            state[0] ^= a; state[1] ^= b; state[2] ^= c; state[3] ^= d;
            state[4] ^= e; state[5] ^= f; state[6] ^= g; state[7] ^= h;
        }

        var result = new byte[32];
        for (var index = 0; index < state.Length; index++)
        {
            BinaryPrimitives.WriteUInt32BigEndian(result.AsSpan(index * 4, 4), state[index]);
        }
        return result;
    }

    private static uint Ff(uint x, uint y, uint z, int j) => j <= 15 ? x ^ y ^ z : (x & y) | (x & z) | (y & z);
    private static uint Gg(uint x, uint y, uint z, int j) => j <= 15 ? x ^ y ^ z : (x & y) | (~x & z);
    private static uint P0(uint x) => x ^ RotateLeft(x, 9) ^ RotateLeft(x, 17);
    private static uint P1(uint x) => x ^ RotateLeft(x, 15) ^ RotateLeft(x, 23);

    private static uint RotateLeft(uint value, int offset) =>
        (value << (offset & 31)) | (value >> ((32 - offset) & 31));
}
