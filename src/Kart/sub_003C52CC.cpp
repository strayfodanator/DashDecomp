// MATCHING sub_003C52CC
extern "C" unsigned sub_003C52CC(void* self) {
    void* ptr;
    asm("ldr %0, [%1, #0x2C]" : "=r"(ptr) : "r"(self));
    return *(unsigned*)((char*)ptr + 0x70) + 0x44;
}
