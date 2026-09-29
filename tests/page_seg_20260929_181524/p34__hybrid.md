16 <!-- bbox=[61, 81, 87, 102] -->

<!-- bbox=[689, 79, 1009, 104] -->
### 第1章 微弱信号检测与随机噪声

例 1-2 随机相位正弦波  $ x(t)=A\sin(\omega_{0}t+\varphi) $， $ \varphi $ 在  $ 0\sim2\pi $ 之间均匀分布，幅度 A 为常数；随机幅度正弦波  $ y(t)=B\sin(\omega_{0}t) $，B 是与  $ \varphi $ 相互独立的随机量，B 的概率密度函数为 <!-- bbox=[54, 133, 1010, 236] -->

$$$$ p(B)=\frac{1}{\sqrt{2\pi}}\exp[-B^{2}/2] $$$$ <!-- bbox=[387, 247, 680, 303] -->

(（1-33a）) <!-- bbox=[924, 257, 1006, 283] -->

试求  $ x(t) $ 和  $ y(t) $ 的统计特征量  $ \mu_{x} $、 $ \sigma_{x}^{2} $、 $ R_{x}(\tau) $、 $ \mu_{y} $、 $ R_{xy}(\tau) $ 和  $ C_{xy}(\tau) $。 <!-- bbox=[52, 315, 751, 343] -->

解：（1） $ x(t) $ 的均值  $ \mu_{x} $ <!-- bbox=[103, 354, 347, 380] -->

$$$$ \begin{array}{l}\mu_{x}=E[x(t)]=\displaystyle\int x(t)p(x)\mathrm{d}x=\int_{0}^{2\pi}A\sin(\omega_{0}t+\varphi)p(\varphi)\mathrm{d}\varphi\\ \quad=\frac{A}{2\pi}\int_{0}^{2\pi}\sin(\omega_{0}t+\varphi)\mathrm{d}\varphi=0\end{array} $$$$ <!-- bbox=[221, 389, 845, 505] -->

(2) $ x(t) $的方差 $ \sigma_{x}^{2} $ <!-- bbox=[106, 517, 302, 543] -->

$$$$ \begin{aligned}\sigma_{x}^{2}&=E[x(t)-\mu_{x}]^{2}=E[A^{2}\sin^{2}(\omega_{0}t+\varphi)]\\&=\frac{A^{2}}{2}E[1-\cos(2\omega_{0}t+2\varphi)]\\&=\frac{A^{2}}{2}-\frac{A^{2}}{2}\frac{1}{2\pi}\int_{0}^{2\pi}\cos(2\omega_{0}t+2\varphi)\mathrm{d}\varphi=\frac{A^{2}}{2}\end{aligned} $$$$ <!-- bbox=[303, 553, 765, 710] -->

(3)  $ x(t) $ 的自相关函数  $ R_{x}(\tau) $ <!-- bbox=[105, 721, 416, 747] -->

$$$$ \begin{aligned}R_{x}(\tau)&=E[x(t)\ x(t-\tau)]\\&=E[A\sin(\omega_{0}t+\varphi)\ A\sin(\omega_{0}(t-\tau)+\varphi)]\\&=A^{2}E[\sin(\omega_{0}t+\varphi)\sin(\omega_{0}(t-\tau)+\varphi)]\\&=\frac{A^{2}}{2}E[\cos(\omega_{0}\tau)-\cos(\omega_{0}(2t-\tau)+2\varphi)]\\&=\frac{A^{2}}{2}\cos(\omega_{0}\tau)-\frac{A^{2}}{2}\frac{1}{2\pi}\int_{0}^{2\pi}\cos(\omega_{0}(2t-\tau)+2\varphi)\mathrm{d}\varphi\\ \end{aligned} $$$$ <!-- bbox=[234, 755, 834, 991] -->

上式右边的第二项积分结果为零，所以 <!-- bbox=[58, 999, 464, 1026] -->

$$$$ R_{x}(\tau)=\frac{A^{2}}{2}cos(\omega_{0}\tau) $$$$ <!-- bbox=[416, 1037, 646, 1088] -->

这也就证明了自相关函数的特点（4）：对于正弦信号，不管其初相位如何，其自相关函数总是以余弦函数的形式出现。 <!-- bbox=[54, 1100, 1009, 1165] -->

(4)  $  y(t)  $ 的均值  $ \mu_{y} $ <!-- bbox=[103, 1174, 302, 1203] -->

对比式(1-12)与式(1-33a)可知， $ y(t) $的幅值B是高斯分布，其均值为零，方差为1，得 <!-- bbox=[101, 1211, 992, 1239] -->

$$$$ \mu_{y}=E[y(t)]=E[B\mathrm{c o s}(\omega_{0}t)]=E[B]E[\mathrm{c o s}(\omega_{0}t)]=0 $$$$ <!-- bbox=[222, 1247, 840, 1277] -->

（5）互相关函数  $ R_{xy}(\tau) $ 和互协方差函数  $ C_{xy}(\tau) $ <!-- bbox=[103, 1285, 596, 1312] -->

因为 B 和  $ \varphi $ 相互独立，所以可得 <!-- bbox=[103, 1322, 445, 1349] -->

$$$$ \begin{aligned}R_{xy}(\tau)&=E[x(t-\tau)y(t)]\\&=E[A\sin(\omega_{0}(t-\tau)+\varphi)B\sin(\omega_{0}t)]\\&=E[A\sin(\omega_{0}(t-\tau)+\varphi)]E[B\sin(\omega_{0}t)]\\&=\mu_{x}\mu_{y}=0\\C_{xy}(\tau)&=R_{xy}(\tau)-\mu_{x}\mu_{y}=0\end{aligned} $$$$ <!-- bbox=[272, 1357, 791, 1530] -->