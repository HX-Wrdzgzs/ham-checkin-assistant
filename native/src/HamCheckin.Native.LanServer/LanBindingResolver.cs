using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;

namespace HamCheckin.Native.LanServer;

public sealed record LanBindingCandidate(
    IPAddress Address,
    string InterfaceName,
    string Description,
    NetworkInterfaceType InterfaceType);

/// <summary>
/// 私网 IPv4 枚举与候选端口（设计文档 3.2）。S2 只暴露，不自动监听。
/// 永不返回 0.0.0.0 / :: 或 169.254/16 地址。
/// </summary>
public static class LanBindingResolver
{
    public const int FirstPort = 8731;
    public const int LastPort = 8740;

    public static IReadOnlyList<int> CandidatePorts { get; } =
        Enumerable.Range(FirstPort, LastPort - FirstPort + 1).ToArray();

    public static IReadOnlyList<LanBindingCandidate> GetPrivateIpv4Candidates()
    {
        var interfaces = NetworkInterface.GetAllNetworkInterfaces();
        var candidates = new List<(LanBindingCandidate Candidate, int InterfaceRank, int InterfaceIndex)>();
        for (var index = 0; index < interfaces.Length; index++)
        {
            var networkInterface = interfaces[index];
            if (networkInterface.OperationalStatus != OperationalStatus.Up
                || networkInterface.NetworkInterfaceType is NetworkInterfaceType.Loopback
                    or NetworkInterfaceType.Tunnel)
            {
                continue;
            }

            IPInterfaceProperties properties;
            try
            {
                properties = networkInterface.GetIPProperties();
            }
            catch (NetworkInformationException)
            {
                continue;
            }

            foreach (var unicast in properties.UnicastAddresses)
            {
                if (unicast.Address.AddressFamily != AddressFamily.InterNetwork
                    || !IsPrivateIpv4(unicast.Address))
                {
                    continue;
                }

                candidates.Add((
                    new LanBindingCandidate(
                        unicast.Address,
                        networkInterface.Name,
                        networkInterface.Description,
                        networkInterface.NetworkInterfaceType),
                    Rank(networkInterface.NetworkInterfaceType),
                    index));
            }
        }

        return candidates
            .OrderBy(static candidate => candidate.InterfaceRank)
            .ThenBy(static candidate => candidate.InterfaceIndex)
            .Select(static candidate => candidate.Candidate)
            .ToArray();
    }

    /// <summary>
    /// 只接受 RFC1918 单播；169.254/16 与回环天然不在范围内。
    /// </summary>
    public static bool IsPrivateIpv4(IPAddress address)
    {
        ArgumentNullException.ThrowIfNull(address);
        if (address.AddressFamily != AddressFamily.InterNetwork)
        {
            return false;
        }

        var bytes = address.GetAddressBytes();
        return bytes[0] == 10
            || (bytes[0] == 172 && bytes[1] is >= 16 and <= 31)
            || (bytes[0] == 192 && bytes[1] == 168);
    }

    private static int Rank(NetworkInterfaceType type) => type switch
    {
        NetworkInterfaceType.Ethernet
            or NetworkInterfaceType.GigabitEthernet
            or NetworkInterfaceType.FastEthernetT
            or NetworkInterfaceType.FastEthernetFx
            or NetworkInterfaceType.Ethernet3Megabit => 0,
        NetworkInterfaceType.Wireless80211 => 1,
        _ => 2
    };
}
