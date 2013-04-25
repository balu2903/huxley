# TODO: keypress and scroll events
# TODO: support page reloads

import contextlib
import math
import operator
import os
import time
import jsonpickle
from selenium import webdriver
import Image
import ImageChops
import plac

def rmsdiff_2011(im1, im2):
    "Calculate the root-mean-square difference between two images"
    diff = ImageChops.difference(im1, im2)
    h = diff.histogram()
    sq = (value*(idx**2) for idx, value in enumerate(h))
    sum_of_squares = sum(sq)
    rms = math.sqrt(sum_of_squares/float(im1.size[0] * im1.size[1]))
    return rms

def images_identical(path1, path2):
    im1 = Image.open(path1)
    im2 = Image.open(path2)
    return ImageChops.difference(im1, im2).getbbox() is None

def image_diff(path1, path2, outpath, diffcolor):
    im1 = Image.open(path1)
    im2 = Image.open(path2)

    rmsdiff = rmsdiff_2011(im1, im2)

    pix1 = im1.load()
    pix2 = im2.load()

    if im1.mode != im2.mode:
        raise ValueError('Different pixel modes between %r and %r' % (path1, path2))
    if im1.size != im2.size:
        raise ValueError('Different dimensions between %r and %r' % (path1, path2))

    mode = im1.mode

    if mode == '1':
        value = 255
    elif mode == 'L':
        value = 255
    elif mode == 'RGB':
        value = diffcolor
    elif mode == 'RGBA':
        value = diffcolor + (255,)
    elif mode == 'P':
        raise NotImplementedError('TODO: look up nearest palette color')
    else:
        raise NotImplementedError('Unexpected PNG mode')

    width,height = im1.size

    for y in xrange(height):
        for x in xrange(width):
            if pix1[x,y] != pix2[x,y]:
                pix2[x, y] = value
    im2.save(outpath)

    return (rmsdiff, width, height)

class TestError(RuntimeError):
    pass

class TestStep(object):
    def __init__(self, offset_time):
        self.offset_time = offset_time

    def execute(self, run):
        raise NotImplementedError

class ClickTestStep(TestStep):
    CLICK_ID = '_jonxClick'
    def __init__(self, offset_time, pos):
        super(ClickTestStep, self).__init__(offset_time)
        self.pos = pos

    def execute(self, run):
        print '  Clicking', self.pos
        # Work around a bug in ActionChains.move_by_offset()
        id = run.d.execute_script('return document.elementFromPoint(%d, %d).id;' % tuple(self.pos))
        if id is None:
            run.d.execute_script('document.elementFromPoint(%d, %d).id = %r;' % (self.pos[0], self.pos[1], self.CLICK_ID))
            id = self.CLICK_ID
        run.d.find_element_by_id(id).click()

class ScreenshotTestStep(TestStep):
    def __init__(self, offset_time, run, index):
        super(ScreenshotTestStep, self).__init__(offset_time)
        self.index = index

    def get_path(self, run):
        return os.path.join(run.path, 'screenshot' + str(self.index) + '.png')

    def execute(self, run):
        print '  Taking screenshot', self.index
        original = self.get_path(run)
        new = os.path.join(run.path, 'last.png')
        if run.mode == TestRunModes.RERECORD:
            run.d.save_screenshot(original)
        else:
            run.d.save_screenshot(new)
            if not images_identical(original, new):
                diffpath = os.path.join(run.path, 'diff.png')
                diff = image_diff(original, new, diffpath, run.diffcolor)
                raise TestError('Screenshot %s was different; compare %s with %s. See %s for the comparison. diff=%r' % (self.index, original, new, diffpath, diff))

class Test(object):
    def __init__(self, screen_size):
        self.steps = []
        self.screen_size = screen_size

class TestRunModes(object):
    RECORD = 1
    RERECORD = 2
    PLAYBACK = 3

class TestRun(object):
    def __init__(self, test, path, url, d, mode, diffcolor):
        self.test = test
        self.path = path
        self.url = url
        self.d = d
        self.mode = mode
        self.diffcolor = diffcolor

    @classmethod
    def rerecord(cls, test, path, url, d, sleepfactor, diffcolor):
        print 'Begin rerecord'
        run = TestRun(test, path, url, d, TestRunModes.RERECORD, diffcolor)
        run._playback(sleepfactor)
        print
        print 'Playing back to ensure the test is correct'
        print
        cls.playback(test, path, url, d, sleepfactor, diffcolor)

    @classmethod
    def playback(cls, test, path, url, d, sleepfactor, diffcolor):
        print 'Begin playback'
        run = TestRun(test, path, url, d, TestRunModes.PLAYBACK, diffcolor)
        run._playback(sleepfactor)

    def _playback(self, sleepfactor):
        self.d.set_window_size(*self.test.screen_size)
        self.d.get('about:blank')
        self.d.refresh()
        self.d.get(self.url)
        last_offset_time = 0
        for step in self.test.steps:
            sleep_time = (step.offset_time - last_offset_time) * sleepfactor
            print '  Sleeping for', sleep_time, 'ms'
            time.sleep(float(sleep_time) / 1000)
            step.execute(self)
            last_offset_time = step.offset_time

    @classmethod
    def record(cls, d, url, screen_size, path, diffcolor, sleepfactor):
        print 'Begin record'
        try:
            os.makedirs(path)
        except:
            pass
        test = Test(screen_size)
        run = TestRun(test, path, url, d, TestRunModes.RECORD, diffcolor)
        d.set_window_size(*screen_size)
        d.get('about:blank')
        d.refresh()
        d.get(run.url)
        start_time = d.execute_script('return Date.now();')
        d.execute_script('''
(function() {
var events = [];
window.addEventListener('click', function (e) { events.push([Date.now(), [e.clientX, e.clientY]]); }, true);
window._getJonxEvents = function() { return events; };
})();
''')
        steps = []
        while True:
            if len(raw_input("Press enter to take a screenshot, or type Q+enter if you're done\n")) > 0:
                break
            screenshot_step = ScreenshotTestStep(d.execute_script('return Date.now();') - start_time, run, len(steps))
            run.d.save_screenshot(screenshot_step.get_path(run))
            steps.append(screenshot_step)
            print len(steps), 'screenshots taken'

        # now capture the clicks
        events = d.execute_script('return window._getJonxEvents();')
        for (timestamp, id) in events:
            steps.append(ClickTestStep(timestamp - start_time, id))

        steps.sort(key=operator.attrgetter('offset_time'))

        test.steps = steps

        print
        raw_input('Up next, we will re-run your actions to generate automated screenshots (this is because Selenium doesn\'t activate hover CSS states). Please pay attention to the test run. Press enter to start.')
        print
        cls.rerecord(test, path, url, d, sleepfactor, diffcolor)

        return test

DRIVERS = {
    'firefox': webdriver.Firefox,
    'chrome': webdriver.Chrome,
    'ie': webdriver.Ie,
    'opera': webdriver.Opera
}

CAPABILITIES = {
    'firefox': webdriver.DesiredCapabilities.FIREFOX,
    'chrome': webdriver.DesiredCapabilities.CHROME,
    'ie': webdriver.DesiredCapabilities.INTERNETEXPLORER,
    'opera': webdriver.DesiredCapabilities.OPERA
}

@plac.annotations(
    filename=plac.Annotation('Test file location'),
    record=plac.Annotation('Record a test', 'flag', 'r', metavar='URL'),
    rerecord=plac.Annotation('Re-run the test but take new screenshots', 'flag', 'R'),
    sleepfactor=plac.Annotation('Sleep interval multiplier', 'option', 'f', float, metavar='FLOAT'),
    browser=plac.Annotation('Browser to use, either firefox, chrome, phantomjs, ie or opera.', 'option', 'b', str, metavar='NAME'),
    remote=plac.Annotation('Remote WebDriver to use', 'option', 'w', metavar='URL'),
    diffcolor=plac.Annotation('Diff color for errors (i.e. 0,255,0)', 'option', 'd', str, metavar='RGB'),
    screensize=plac.Annotation('Width and height for screen (i.e. 1024x768)', 'option', 's', metavar='SIZE'),
)
def main(url, filename, record=False, rerecord=False, sleepfactor=1.0, browser='firefox', remote=None, diffcolor='0,255,0', screensize='1024x768'):
    try:
        if remote:
            d = webdriver.Remote(remote, CAPABILITIES[browser])
        else:
            d = DRIVERS[browser]()
        screensize = tuple(int(x) for x in screensize.split('x'))
    except KeyError:
        raise ValueError(
            'Invalid browser %r; valid browsers are %r.' % (browser, DRIVERS.keys())
        )

    try:
        os.makedirs(filename)
    except:
        pass

    diffcolor = tuple(int(x) for x in diffcolor.split(','))
    jsonfile = os.path.join(filename, 'record.json')

    with contextlib.closing(d):
        if record:
            with open(jsonfile, 'w') as f:
                f.write(jsonpickle.encode(TestRun.record(d, url, screensize, filename, diffcolor, sleepfactor)))
                print 'Test recorded successfully'
        elif rerecord:
            with open(jsonfile, 'r') as f:
                TestRun.rerecord(jsonpickle.decode(f.read()), filename, url, d, sleepfactor, diffcolor)
                print 'Test rerecorded successfully'
        else:
            with open(jsonfile, 'r') as f:
                TestRun.playback(jsonpickle.decode(f.read()), filename, url, d, sleepfactor, diffcolor)
                print 'Test played back successfully'

if __name__ == '__main__':
    plac.call(main)
