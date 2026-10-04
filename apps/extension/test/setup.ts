// jsdom has no DataTransfer; Chrome does. A minimal stand-in for attach_file tests.
class FakeDataTransfer {
  private list: File[] = [];
  items = { add: (f: File) => this.list.push(f) };
  get files(): FileList {
    const arr = [...this.list];
    return Object.assign(arr, { item: (i: number) => arr[i] ?? null }) as unknown as FileList;
  }
}
(globalThis as unknown as { DataTransfer: unknown }).DataTransfer = FakeDataTransfer;
// jsdom refuses to assign a non-FileList to input.files; allow it like a browser would accept dt.files
Object.defineProperty(HTMLInputElement.prototype, "files", {
  configurable: true,
  get(this: HTMLInputElement & { _files?: FileList }) {
    return this._files ?? null;
  },
  set(this: HTMLInputElement & { _files?: FileList }, v: FileList) {
    this._files = v;
  },
});
