import peer

msg = "hello from A"
c1 = peer.encrypt_text(msg)
c2 = peer.encrypt_text(msg)

print("plain text    :", msg)
print("ciphertext 1  :", c1)
print("ciphertext 2  :", c2)
print("same text, different ciphertext:", c1 != c2)
print("decrypted     :", peer.decrypt_text(c1))

# Tampering: flip one character
t = list(c1)
t[20] = "A" if t[20] != "A" else "B"
print("tampered      :", peer.decrypt_text("".join(t)))

# Wrong password: swap the signing key
good = peer._MAC_KEY
peer._MAC_KEY = b"x" * 32
print("wrong password:", peer.decrypt_text(c1))
peer._MAC_KEY = good