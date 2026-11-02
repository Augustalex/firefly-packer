#import <Cocoa/Cocoa.h>
#include <errno.h>
#include <unistd.h>

// Packaging helper only. The bundled Firefly executable runs the game.
static BOOL copyFiles(NSURL *source, NSURL *destination, BOOL replace, NSError **error) {
    NSFileManager *files = NSFileManager.defaultManager;
    BOOL directory = NO;
    if (![files fileExistsAtPath:source.path isDirectory:&directory]) {
        if (error) *error = [NSError errorWithDomain:NSCocoaErrorDomain
            code:NSFileReadNoSuchFileError userInfo:@{NSFilePathErrorKey: source.path}];
        return NO;
    }
    if (directory) {
        if (![files createDirectoryAtURL:destination withIntermediateDirectories:YES
                            attributes:nil error:error]) return NO;
        NSArray<NSURL *> *children = [files contentsOfDirectoryAtURL:source
            includingPropertiesForKeys:nil options:0 error:error];
        if (!children) return NO;
        for (NSURL *child in children) {
            NSURL *target = [destination URLByAppendingPathComponent:child.lastPathComponent];
            if (!copyFiles(child, target, replace, error)) return NO;
        }
        return YES;
    }
    if (!replace && [files fileExistsAtPath:destination.path]) return YES;
    NSData *data = [NSData dataWithContentsOfURL:source options:0 error:error];
    return data && [data writeToURL:destination options:NSDataWritingAtomic error:error];
}

static int showError(NSString *message, NSError *error) {
    NSString *details = error ? [message stringByAppendingFormat:@"\n\n%@", error.localizedDescription] : message;
    fprintf(stderr, "Game: %s\n", details.UTF8String);
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [NSApp finishLaunching];
    [NSApp activateIgnoringOtherApps:YES];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.alertStyle = NSAlertStyleCritical;
    NSString *name = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleDisplayName"] ?: @"Game";
    alert.messageText = [name stringByAppendingString:@" could not start"];
    alert.informativeText = details;
    [alert addButtonWithTitle:@"Quit"];
    [alert runModal];
    return 1;
}

int main(void) {
    @autoreleasepool {
        NSBundle *bundle = NSBundle.mainBundle;
        NSURL *resources = bundle.resourceURL;
        NSString *appID = [bundle objectForInfoDictionaryKey:@"FireflyAppID"];
        if (!resources || !appID.length) {
            return showError(@"The app package is incomplete. Extract a fresh copy of the app from its ZIP.", nil);
        }
        NSString *override = NSProcessInfo.processInfo.environment[@"FIREFLY_PACKER_DATA_DIR"];
        NSString *dataPath = override.length ? override :
            [[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support"]
                stringByAppendingPathComponent:[bundle objectForInfoDictionaryKey:@"FireflyDataFolder"]];
        NSURL *data = [NSURL fileURLWithPath:dataPath isDirectory:YES];
        NSError *error = nil;
        if (!copyFiles([resources URLByAppendingPathComponent:@"initial-vfs"], data, NO, &error)) {
            return showError(@"Game could not prepare its save folder. Check that you can write to it.", error);
        }
        if (!copyFiles([resources URLByAppendingPathComponent:@"roms"],
                       [data URLByAppendingPathComponent:@"roms"], YES, &error)) {
            return showError(@"Game could not prepare its game files. Extract a fresh copy of the app and try again.", error);
        }
        NSURL *emulator = [bundle.executableURL.URLByDeletingLastPathComponent
            URLByAppendingPathComponent:@"firefly-emulator"];
        NSString *title = [bundle objectForInfoDictionaryKey:@"CFBundleDisplayName"];
        NSString *scale = [[bundle objectForInfoDictionaryKey:@"FireflyScale"] stringValue];
        const char *arguments[] = {title.UTF8String, "--vfs", data.fileSystemRepresentation,
            "--id", appID.UTF8String, "--scale", scale.UTF8String, "--title", title.UTF8String, NULL};
        // Replace this process so closing the game cannot leave a launcher behind.
        execv(emulator.fileSystemRepresentation, (char *const *)arguments);
        error = [NSError errorWithDomain:NSPOSIXErrorDomain code:errno userInfo:nil];
        return showError(@"The bundled emulator could not launch. Extract a fresh copy of Game.app and try again.", error);
    }
}
