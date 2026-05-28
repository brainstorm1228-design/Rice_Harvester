namespace Agent.Network;

using System.Security.Cryptography;
using System.Text;

public static class Crypto
{
    public static byte[] DeriveKey(string secret)
        => SHA256.HashData(Encoding.UTF8.GetBytes(secret));

    // 암호화: [16B IV][AES-CBC 암호문]
    public static byte[] Encrypt(byte[] plaintext, byte[] key)
    {
        using var aes = Aes.Create();
        aes.Key = key;
        aes.GenerateIV();

        using var enc = aes.CreateEncryptor();
        var cipher = enc.TransformFinalBlock(plaintext, 0, plaintext.Length);

        var result = new byte[16 + cipher.Length];
        aes.IV.CopyTo(result, 0);
        cipher.CopyTo(result, 16);
        return result;
    }

    // 복호화: 앞 16B를 IV로 사용
    public static byte[] Decrypt(byte[] data, byte[] key)
    {
        using var aes = Aes.Create();
        aes.Key = key;
        aes.IV = data[..16];

        using var dec = aes.CreateDecryptor();
        return dec.TransformFinalBlock(data, 16, data.Length - 16);
    }
}
